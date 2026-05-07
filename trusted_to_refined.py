import json
import os
import time
import urllib.request
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

from etl_utils import (
    append_processed_file,
    ensure_directory,
    iso_now,
    load_processed_files,
    read_json_file,
    write_json_file,
)
from location_cache import (
    LocalLocationIndex,
    PersistentGeocodingCache,
    city_state_key,
    normalize_optional_text,
)

load_dotenv()

MONTH_COLUMNS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
GROUP_KEYS = ["state", "city", "suburb", "postcode"]
UNKNOWN_TEXT = "desconhecido"


def env_flag(name, default):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def reverse_geocode(lat, lon, user_agent, remote_delay_seconds):
    base_url = "https://nominatim.openstreetmap.org/reverse?format=json"
    url = f"{base_url}&lat={lat}&lon={lon}"
    headers = {"User-Agent": user_agent}

    try:
        if remote_delay_seconds > 0:
            time.sleep(remote_delay_seconds)

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            if response.getcode() != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Geo] Erro: {e}")
        return None


def calculate_seasons(monthly_data):
    return {
        "summer_avg": round((monthly_data.get("JAN", 0) + monthly_data.get("FEB", 0) + monthly_data.get("DEC", 0)) / 3, 1),
        "autumn_avg": round((monthly_data.get("MAR", 0) + monthly_data.get("APR", 0) + monthly_data.get("MAY", 0)) / 3, 1),
        "winter_avg": round((monthly_data.get("JUN", 0) + monthly_data.get("JUL", 0) + monthly_data.get("AUG", 0)) / 3, 1),
        "spring_avg": round((monthly_data.get("SEP", 0) + monthly_data.get("OCT", 0) + monthly_data.get("NOV", 0)) / 3, 1),
    }


def extract_normalized_address(geo_data):
    if not geo_data:
        return None

    addr = geo_data.get("address", {})
    city = (
        addr.get("city")
        or addr.get("city_district")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
    )
    state = addr.get("state")

    return {
        "city": normalize_optional_text(city),
        "state": normalize_optional_text(state),
        "suburb": normalize_optional_text(addr.get("suburb") or addr.get("neighbourhood") or addr.get("hamlet")),
        "postcode": normalize_optional_text(addr.get("postcode")),
        "road": normalize_optional_text(addr.get("road") or addr.get("street") or addr.get("pedestrian")),
        "full_address": normalize_optional_text(geo_data.get("display_name")),
    }


def build_local_location_index(refined_path):
    index = LocalLocationIndex()

    if not os.path.exists(refined_path):
        return index

    for root, _, files in os.walk(refined_path):
        for file_name in files:
            if not file_name.endswith(".json"):
                continue
            if "_meta_" in file_name or "_manifest_" in file_name:
                continue
            if not (
                file_name.startswith("solar_data_refined_")
                or file_name.startswith("solar_data_rejected_")
            ):
                continue

            file_path = os.path.join(root, file_name)
            records = read_json_file(file_path, default=[])
            if not isinstance(records, list):
                continue

            for record in records:
                if not isinstance(record, dict):
                    continue

                lat = record.get("lat")
                lon = record.get("lon")
                city = record.get("city")
                state = record.get("state")

                if lat is None or lon is None or city is None or state is None:
                    continue

                index.add_record(record)

    return index


def build_existing_ibge_lookup(ibge_path):
    lookup = {}

    if not os.path.exists(ibge_path):
        return lookup

    for root, _, files in os.walk(ibge_path):
        for file_name in files:
            if not file_name.startswith("solar_data_ibge_") or not file_name.endswith(".json"):
                continue

            records = read_json_file(os.path.join(root, file_name), default=[])
            if not isinstance(records, list):
                continue

            for record in records:
                if not isinstance(record, dict):
                    continue

                if record.get("ibge_match_status") != "matched":
                    continue

                key = city_state_key(record.get("city"), record.get("state"))
                if key == "|":
                    continue

                lookup[key] = {
                    "ibge_city_code": record.get("ibge_city_code"),
                    "ibge_city_name": record.get("ibge_city_name"),
                    "ibge_state_name": record.get("ibge_state_name"),
                    "ibge_state_acronym": record.get("ibge_state_acronym"),
                }

    return lookup


def resolve_location(
    reading,
    local_index,
    persistent_cache,
    ibge_lookup,
    user_agent,
    remote_delay_seconds,
    fast_mode,
    detailed_mode,
    max_distance_km,
    stats,
):
    lat = reading["lat"]
    lon = reading["lon"]

    cached = persistent_cache.get(lat, lon)
    if cached is not None:
        stats["cache_hit"] += 1
        location = {**cached}
        if location.get("city") and location.get("state"):
            ibge_data = ibge_lookup.get(city_state_key(location.get("city"), location.get("state")))
            if ibge_data:
                location.update(ibge_data)
        return location

    stats["cache_miss"] += 1

    local_match = local_index.lookup(lat, lon, max_distance_km=max_distance_km)
    if local_match is not None:
        stats[local_match["lookup_source"]] += 1
        ibge_data = ibge_lookup.get(city_state_key(local_match.get("city"), local_match.get("state")))
        normalized = {
            "city": local_match.get("city"),
            "state": local_match.get("state") or reading.get("state"),
            "suburb": local_match.get("suburb"),
            "postcode": local_match.get("postcode"),
            "road": local_match.get("road"),
            "full_address": local_match.get("full_address"),
            "lookup_source": local_match.get("lookup_source"),
        }
        if ibge_data:
            normalized.update(ibge_data)
        persistent_cache.set(lat, lon, normalized)
        return normalized

    should_use_remote = detailed_mode or not fast_mode
    if should_use_remote:
        stats["remote_calls"] += 1
        geo_data = reverse_geocode(lat, lon, user_agent, remote_delay_seconds)
        normalized = extract_normalized_address(geo_data) or {}
        normalized["lookup_source"] = "remote_nominatim"
        normalized["state"] = reading.get("state") or normalized.get("state")
        if normalized.get("city") and normalized.get("state"):
            ibge_data = ibge_lookup.get(city_state_key(normalized.get("city"), normalized.get("state")))
            if ibge_data:
                normalized.update(ibge_data)
        if normalized.get("city") or normalized.get("suburb") or normalized.get("postcode"):
            persistent_cache.set(lat, lon, normalized)
            return normalized

        stats["remote_failures"] += 1

    return {
        "city": None,
        "state": normalize_optional_text(reading.get("state")),
        "suburb": None,
        "postcode": None,
        "road": None,
        "full_address": None,
        "lookup_source": "unresolved",
    }


def aggregate_records(valid_records):
    df = pd.DataFrame(valid_records)
    required_columns = GROUP_KEYS + ["id", "lat", "lon", "annual", *MONTH_COLUMNS, "summer_avg", "autumn_avg", "winter_avg", "spring_avg"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Colunas ausentes para agregacao refined: {missing_columns}")

    aggregated = (
        df.groupby(GROUP_KEYS, dropna=False)
        .agg(
            points_count=("id", "count"),
            avg_lat=("lat", "mean"),
            avg_lon=("lon", "mean"),
            annual_avg=("annual", "mean"),
            jan_avg=("JAN", "mean"),
            feb_avg=("FEB", "mean"),
            mar_avg=("MAR", "mean"),
            apr_avg=("APR", "mean"),
            may_avg=("MAY", "mean"),
            jun_avg=("JUN", "mean"),
            jul_avg=("JUL", "mean"),
            aug_avg=("AUG", "mean"),
            sep_avg=("SEP", "mean"),
            oct_avg=("OCT", "mean"),
            nov_avg=("NOV", "mean"),
            dec_avg=("DEC", "mean"),
            summer_avg=("summer_avg", "mean"),
            autumn_avg=("autumn_avg", "mean"),
            winter_avg=("winter_avg", "mean"),
            spring_avg=("spring_avg", "mean"),
            ibge_city_code=("ibge_city_code", "first"),
            ibge_city_name=("ibge_city_name", "first"),
            ibge_state_name=("ibge_state_name", "first"),
            ibge_state_acronym=("ibge_state_acronym", "first"),
        )
        .reset_index()
    )

    numeric_columns = [
        "avg_lat", "avg_lon", "annual_avg",
        "jan_avg", "feb_avg", "mar_avg", "apr_avg", "may_avg", "jun_avg",
        "jul_avg", "aug_avg", "sep_avg", "oct_avg", "nov_avg", "dec_avg",
        "summer_avg", "autumn_avg", "winter_avg", "spring_avg",
    ]

    for col in numeric_columns:
        aggregated[col] = aggregated[col].round(1)

    optional_columns = [
        "suburb",
        "postcode",
        "ibge_city_code",
        "ibge_city_name",
        "ibge_state_name",
        "ibge_state_acronym",
    ]
    for col in optional_columns:
        aggregated[col] = aggregated[col].astype(object).where(pd.notna(aggregated[col]), None)

    return aggregated.to_dict(orient="records")


def process_trusted_to_refined():
    trusted_path = os.getenv("TRUSTED_DATA_PATH", "data/trusted")
    refined_path = os.getenv("REFINED_DATA_PATH", "data/refined")
    ibge_path = os.getenv("IBGE_DATA_PATH", "data/ibge")
    user_agent = os.getenv("NOMINATIM_USER_AGENT", "SolarIrradiationPipeline/2.0")
    fast_mode = env_flag("REFINED_FAST_MODE", True)
    detailed_mode = env_flag("REFINED_DETAILED_MODE", False)
    require_detailed_location = env_flag("REFINED_REQUIRE_DETAILED_LOCATION", False)
    remote_delay_seconds = float(os.getenv("GEOCODING_REMOTE_DELAY_SECONDS", "1.1"))
    local_match_max_distance_km = float(os.getenv("LOCAL_LOCATION_MAX_DISTANCE_KM", "18"))

    cache_root = os.getenv("GEOCODING_CACHE_PATH", os.path.join("data", "cache", "geocoding"))
    cache_provider = "nominatim"
    cache_mode = "detailed" if detailed_mode else "fast"
    persistent_cache = PersistentGeocodingCache(cache_root, cache_provider, cache_mode)
    local_index = build_local_location_index(refined_path)
    ibge_lookup = build_existing_ibge_lookup(ibge_path)

    ensure_directory(refined_path)

    for root, _, files in os.walk(trusted_path):
        processed_log = os.path.join(root, ".processed")
        processed_files = load_processed_files(processed_log)
        json_files = [
            f for f in files
            if (
                f.startswith("solar_data_trusted_")
                and f.endswith(".json")
                and "_meta_" not in f
                and "_manifest_" not in f
                and f not in processed_files
            )
        ]

        for file_name in json_files:
            file_path = os.path.join(root, file_name)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Refinando e agregando: {file_name}")
            started_at = time.perf_counter()

            stats = {
                "records_read": 0,
                "records_valid": 0,
                "records_rejected": 0,
                "records_aggregated": 0,
                "cache_hit": 0,
                "cache_miss": 0,
                "local_exact": 0,
                "local_nearest": 0,
                "remote_calls": 0,
                "remote_failures": 0,
            }

            try:
                readings = read_json_file(file_path, default=[])
                if not isinstance(readings, list):
                    raise ValueError(
                        "Arquivo trusted invalido para processamento: esperado JSON array de registros."
                    )
                stats["records_read"] = len(readings)

                valid_records = []
                rejected_records = []

                for reading in readings:
                    seasons = calculate_seasons(reading["monthly_data"])
                    location = resolve_location(
                        reading=reading,
                        local_index=local_index,
                        persistent_cache=persistent_cache,
                        ibge_lookup=ibge_lookup,
                        user_agent=user_agent,
                        remote_delay_seconds=remote_delay_seconds,
                        fast_mode=fast_mode,
                        detailed_mode=detailed_mode,
                        max_distance_km=local_match_max_distance_km,
                        stats=stats,
                    )

                    city = normalize_optional_text(location.get("city"))
                    state = normalize_optional_text(location.get("state") or reading.get("state"))
                    suburb = normalize_optional_text(location.get("suburb"))
                    postcode = normalize_optional_text(location.get("postcode"))

                    reject_reason = None
                    if city is None or state is None:
                        reject_reason = "missing_required_core_location_fields"
                    elif require_detailed_location and (suburb is None or postcode is None):
                        reject_reason = "missing_required_detailed_location_fields"

                    if reject_reason:
                        rejected_records.append({
                            "id": reading["id"],
                            "lat": reading["lat"],
                            "lon": reading["lon"],
                            "state": state,
                            "city": city or UNKNOWN_TEXT,
                            "suburb": suburb or UNKNOWN_TEXT,
                            "postcode": postcode or UNKNOWN_TEXT,
                            "lookup_source": location.get("lookup_source"),
                            "reject_reason": reject_reason,
                        })
                        stats["records_rejected"] += 1
                        continue

                    valid_records.append({
                        "id": reading["id"],
                        "lat": float(reading["lat"]),
                        "lon": float(reading["lon"]),
                        "state": state,
                        "city": city,
                        "suburb": suburb,
                        "postcode": postcode,
                        "annual": round(float(reading["annual"]), 1),
                        **{month: round(float(reading["monthly_data"].get(month, 0)), 1) for month in MONTH_COLUMNS},
                        **seasons,
                        "ibge_city_code": location.get("ibge_city_code"),
                        "ibge_city_name": location.get("ibge_city_name"),
                        "ibge_state_name": location.get("ibge_state_name"),
                        "ibge_state_acronym": location.get("ibge_state_acronym"),
                    })

                stats["records_valid"] = len(valid_records)
                aggregated_records = aggregate_records(valid_records) if valid_records else []
                stats["records_aggregated"] = len(aggregated_records)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                date_folder = os.path.basename(root)
                target_dir = os.path.join(refined_path, date_folder)
                ensure_directory(target_dir)

                data_file = os.path.join(target_dir, f"solar_data_refined_{timestamp}.json")
                rejected_file = os.path.join(target_dir, f"solar_data_rejected_{timestamp}.json")

                if aggregated_records:
                    write_json_file(data_file, aggregated_records)

                if rejected_records:
                    write_json_file(rejected_file, rejected_records)

                finished_at = time.perf_counter()
                append_processed_file(processed_log, file_name)

                print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros validos: {stats['records_valid']}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros agregados: {stats['records_aggregated']}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Cache hit/miss: {stats['cache_hit']}/{stats['cache_miss']}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Tempo total: {round(finished_at - started_at, 3)}s")
                if aggregated_records:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: {data_file}")
                if rejected_records:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Rejeitados em: {rejected_file}")

            except Exception as e:
                print(f"Erro ao refinar {file_name}: {e}")


if __name__ == "__main__":
    process_trusted_to_refined()
