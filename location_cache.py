import hashlib
import math
import os

from etl_utils import ensure_directory, read_json_file, write_json_file


UNKNOWN_TEXT = "desconhecido"


def normalize_text(value):
    if value is None:
        return ""

    text = str(value).strip()
    if not text or text.lower() == UNKNOWN_TEXT:
        return ""

    return text


def normalize_optional_text(value):
    text = normalize_text(value)
    return text or None


def coordinate_key(lat, lon, precision=4):
    return f"{round(float(lat), precision):.{precision}f}|{round(float(lon), precision):.{precision}f}"


def city_state_key(city, state):
    city_text = normalize_text(city).casefold()
    state_text = normalize_text(state).casefold()
    return f"{city_text}|{state_text}"


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


class PersistentGeocodingCache:
    def __init__(self, cache_dir, provider, mode):
        self.cache_dir = cache_dir
        self.provider = provider
        self.mode = mode
        ensure_directory(self.cache_dir)

    def _path_for(self, lat, lon):
        digest = hashlib.sha1(
            f"{self.provider}|{self.mode}|{coordinate_key(lat, lon)}".encode("utf-8")
        ).hexdigest()
        return os.path.join(self.cache_dir, f"{digest}.json")

    def get(self, lat, lon):
        path = self._path_for(lat, lon)
        return read_json_file(path)

    def set(self, lat, lon, payload):
        path = self._path_for(lat, lon)
        write_json_file(path, payload)


class LocalLocationIndex:
    def __init__(self):
        self.exact = {}
        self.points = []

    def add_record(self, record):
        city = normalize_optional_text(record.get("city"))
        state = normalize_optional_text(record.get("state"))
        lat = record.get("lat")
        lon = record.get("lon")

        if city is None or state is None or lat is None or lon is None:
            return

        normalized = {
            "lat": float(lat),
            "lon": float(lon),
            "city": city,
            "state": state,
            "suburb": normalize_optional_text(record.get("suburb")),
            "postcode": normalize_optional_text(record.get("postcode")),
            "road": normalize_optional_text(record.get("road")),
            "full_address": normalize_optional_text(record.get("full_address")),
        }

        key = coordinate_key(lat, lon)
        existing = self.exact.get(key)
        if existing is None:
            self.exact[key] = normalized
            self.points.append(normalized)
            return

        if existing.get("suburb") is None and normalized.get("suburb") is not None:
            existing["suburb"] = normalized["suburb"]
        if existing.get("postcode") is None and normalized.get("postcode") is not None:
            existing["postcode"] = normalized["postcode"]
        if existing.get("road") is None and normalized.get("road") is not None:
            existing["road"] = normalized["road"]
        if existing.get("full_address") is None and normalized.get("full_address") is not None:
            existing["full_address"] = normalized["full_address"]

    def lookup(self, lat, lon, max_distance_km):
        key = coordinate_key(lat, lon)
        exact = self.exact.get(key)
        if exact is not None:
            return {**exact, "lookup_source": "local_exact"}

        best_match = None
        best_distance = None
        lat_value = float(lat)
        lon_value = float(lon)

        for point in self.points:
            distance = haversine_km(lat_value, lon_value, point["lat"], point["lon"])
            if distance > max_distance_km:
                continue

            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_match = point

        if best_match is None:
            return None

        return {
            **best_match,
            "lookup_source": "local_nearest",
            "distance_km": round(best_distance, 3),
        }
