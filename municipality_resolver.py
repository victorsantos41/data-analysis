import json
import math


DEFAULT_TILE_SIZE = 0.5


def coordinate_cache_key(lat, lon, precision=6):
    return f"{float(lat):.{precision}f}|{float(lon):.{precision}f}"


def normalize_text(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def point_on_segment(point_x, point_y, ax, ay, bx, by, tolerance=1e-9):
    cross = (point_y - ay) * (bx - ax) - (point_x - ax) * (by - ay)
    if abs(cross) > tolerance:
        return False

    dot = (point_x - ax) * (bx - ax) + (point_y - ay) * (by - ay)
    if dot < -tolerance:
        return False

    squared_length = (bx - ax) ** 2 + (by - ay) ** 2
    if dot - squared_length > tolerance:
        return False

    return True


def point_in_ring(point_x, point_y, ring):
    inside = False
    total_points = len(ring)

    if total_points < 3:
        return False

    for index in range(total_points):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % total_points]

        if point_on_segment(point_x, point_y, x1, y1, x2, y2):
            return True

        intersects = ((y1 > point_y) != (y2 > point_y))
        if not intersects:
            continue

        denominator = y2 - y1
        if abs(denominator) < 1e-12:
            continue

        x_intersection = x1 + (point_y - y1) * (x2 - x1) / denominator
        if x_intersection >= point_x:
            inside = not inside

    return inside


def point_in_polygon(point_x, point_y, polygon):
    rings = polygon["rings"]
    if not rings:
        return False

    outer_ring = rings[0]
    if not point_in_ring(point_x, point_y, outer_ring):
        return False

    for inner_ring in rings[1:]:
        if point_in_ring(point_x, point_y, inner_ring):
            return False

    return True


def compute_bbox(ring):
    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    return {
        "min_lon": min(lons),
        "max_lon": max(lons),
        "min_lat": min(lats),
        "max_lat": max(lats),
    }


def bbox_contains(bbox, lon, lat):
    return (
        bbox["min_lon"] <= lon <= bbox["max_lon"]
        and bbox["min_lat"] <= lat <= bbox["max_lat"]
    )


def centroid_from_ring(ring):
    if not ring:
        return 0.0, 0.0

    unique_points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    total_lon = sum(point[0] for point in unique_points)
    total_lat = sum(point[1] for point in unique_points)
    size = len(unique_points) or 1
    return total_lon / size, total_lat / size


def geometry_to_polygons(geometry):
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])

    if geometry_type == "Polygon":
        return [coordinates]
    if geometry_type == "MultiPolygon":
        return coordinates

    return []


class MunicipalityResolver:
    def __init__(self, geojson_path, municipalities_path, cache_path=None, tile_size=DEFAULT_TILE_SIZE):
        self.geojson_path = geojson_path
        self.municipalities_path = municipalities_path
        self.cache_path = cache_path
        self.tile_size = tile_size
        self.cache = {}
        self.cache_dirty = False
        self.municipalities = []
        self.tile_index = {}
        self.stats = {
            "cache_hits": 0,
            "polygon_matches": 0,
            "nearest_matches": 0,
            "unresolved": 0,
        }
        self._load()

    def _load(self):
        with open(self.geojson_path, "r", encoding="utf-8") as f:
            geojson = json.load(f)

        with open(self.municipalities_path, "r", encoding="utf-8") as f:
            municipality_rows = json.load(f) or []

        metadata_by_code = {}
        for row in municipality_rows:
            municipality_code = str(row.get("id"))
            if not municipality_code:
                continue

            metadata_by_code[municipality_code] = {
                "city": normalize_text(row.get("nome")),
                "state": normalize_text(
                    row.get("microrregiao", {})
                    .get("mesorregiao", {})
                    .get("UF", {})
                    .get("nome")
                ),
                "ibge_city_code": int(row.get("id")),
                "ibge_city_name": normalize_text(row.get("nome")),
                "ibge_state_name": normalize_text(
                    row.get("microrregiao", {})
                    .get("mesorregiao", {})
                    .get("UF", {})
                    .get("nome")
                ),
                "ibge_state_acronym": normalize_text(
                    row.get("microrregiao", {})
                    .get("mesorregiao", {})
                    .get("UF", {})
                    .get("sigla")
                ),
            }

        for feature in geojson.get("features", []):
            municipality_code = str(feature.get("properties", {}).get("codarea"))
            metadata = metadata_by_code.get(municipality_code)
            if not metadata:
                continue

            polygons = []
            overall_bbox = None
            centroid_lon_total = 0.0
            centroid_lat_total = 0.0
            centroid_count = 0

            for polygon_coordinates in geometry_to_polygons(feature.get("geometry", {})):
                if not polygon_coordinates:
                    continue

                rings = [
                    [(float(lon), float(lat)) for lon, lat in ring]
                    for ring in polygon_coordinates
                    if ring
                ]
                if not rings:
                    continue

                bbox = compute_bbox(rings[0])
                polygons.append({"rings": rings, "bbox": bbox})

                centroid_lon, centroid_lat = centroid_from_ring(rings[0])
                centroid_lon_total += centroid_lon
                centroid_lat_total += centroid_lat
                centroid_count += 1

                if overall_bbox is None:
                    overall_bbox = dict(bbox)
                else:
                    overall_bbox["min_lon"] = min(overall_bbox["min_lon"], bbox["min_lon"])
                    overall_bbox["max_lon"] = max(overall_bbox["max_lon"], bbox["max_lon"])
                    overall_bbox["min_lat"] = min(overall_bbox["min_lat"], bbox["min_lat"])
                    overall_bbox["max_lat"] = max(overall_bbox["max_lat"], bbox["max_lat"])

            if not polygons or overall_bbox is None or centroid_count == 0:
                continue

            municipality = {
                **metadata,
                "bbox": overall_bbox,
                "polygons": polygons,
                "centroid_lon": centroid_lon_total / centroid_count,
                "centroid_lat": centroid_lat_total / centroid_count,
            }
            municipality_index = len(self.municipalities)
            self.municipalities.append(municipality)
            self._index_bbox(municipality_index, overall_bbox)

    def _tile_key(self, lon, lat):
        return (
            math.floor(lon / self.tile_size),
            math.floor(lat / self.tile_size),
        )

    def _index_bbox(self, municipality_index, bbox):
        min_tile_x = math.floor(bbox["min_lon"] / self.tile_size)
        max_tile_x = math.floor(bbox["max_lon"] / self.tile_size)
        min_tile_y = math.floor(bbox["min_lat"] / self.tile_size)
        max_tile_y = math.floor(bbox["max_lat"] / self.tile_size)

        for tile_x in range(min_tile_x, max_tile_x + 1):
            for tile_y in range(min_tile_y, max_tile_y + 1):
                key = (tile_x, tile_y)
                self.tile_index.setdefault(key, []).append(municipality_index)

    def _cache_result(self, lat, lon, payload):
        key = coordinate_cache_key(lat, lon)
        self.cache[key] = payload
        self.cache_dirty = True

    def _cached(self, lat, lon):
        key = coordinate_cache_key(lat, lon)
        return self.cache.get(key)

    def _candidate_indices(self, lon, lat):
        primary = self.tile_index.get(self._tile_key(lon, lat), [])
        if primary:
            return primary

        tile_x, tile_y = self._tile_key(lon, lat)
        candidates = []
        for delta_x in (-1, 0, 1):
            for delta_y in (-1, 0, 1):
                candidates.extend(self.tile_index.get((tile_x + delta_x, tile_y + delta_y), []))
        return candidates

    def _resolve_from_geometry(self, lat, lon):
        lon_value = float(lon)
        lat_value = float(lat)
        candidates = self._candidate_indices(lon_value, lat_value)

        for municipality_index in candidates:
            municipality = self.municipalities[municipality_index]
            if not bbox_contains(municipality["bbox"], lon_value, lat_value):
                continue

            for polygon in municipality["polygons"]:
                if not bbox_contains(polygon["bbox"], lon_value, lat_value):
                    continue

                if point_in_polygon(lon_value, lat_value, polygon):
                    return {
                        "matched": True,
                        "lookup_source": "municipality_polygon",
                        "city": municipality["city"],
                        "state": municipality["state"],
                        "ibge_city_code": municipality["ibge_city_code"],
                        "ibge_city_name": municipality["ibge_city_name"],
                        "ibge_state_name": municipality["ibge_state_name"],
                        "ibge_state_acronym": municipality["ibge_state_acronym"],
                    }

        nearest = None
        nearest_distance = None
        for municipality in self.municipalities:
            distance_km = haversine_km(
                lat_value,
                lon_value,
                municipality["centroid_lat"],
                municipality["centroid_lon"],
            )
            if nearest_distance is None or distance_km < nearest_distance:
                nearest_distance = distance_km
                nearest = municipality

        if nearest is None or nearest_distance is None or nearest_distance > 50:
            return {
                "matched": False,
                "lookup_source": "unresolved",
            }

        return {
            "matched": True,
            "lookup_source": "municipality_nearest",
            "distance_km": round(nearest_distance, 3),
            "city": nearest["city"],
            "state": nearest["state"],
            "ibge_city_code": nearest["ibge_city_code"],
            "ibge_city_name": nearest["ibge_city_name"],
            "ibge_state_name": nearest["ibge_state_name"],
            "ibge_state_acronym": nearest["ibge_state_acronym"],
        }

    def resolve(self, lat, lon):
        cached = self._cached(lat, lon)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return cached

        resolved = self._resolve_from_geometry(lat, lon)
        self._cache_result(lat, lon, resolved)

        if not resolved.get("matched"):
            self.stats["unresolved"] += 1
        elif resolved.get("lookup_source") == "municipality_nearest":
            self.stats["nearest_matches"] += 1
        else:
            self.stats["polygon_matches"] += 1

        return resolved

    def save_cache(self):
        return
