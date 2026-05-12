import boto3
import json
import os
from datetime import datetime
from urllib.parse import unquote_plus
from municipality_resolver import MunicipalityResolver

s3 = boto3.client("s3")

TRUSTED_BUCKET = os.getenv("TRUSTED_BUCKET", "solarway-trusted")
REFINED_BUCKET = os.getenv("REFINED_BUCKET", "solarway-refined")
SUPPORT_BUCKET = os.getenv("SUPPORT_BUCKET", "solarway-support")

SUPPORT_IBGE_GEOJSON_KEY = os.getenv(
    "SUPPORT_IBGE_GEOJSON_KEY",
    "ibge/ibge_sp_municipios_geo_fixed.geojson",
)
SUPPORT_IBGE_MUNICIPALITIES_KEY = os.getenv(
    "SUPPORT_IBGE_MUNICIPALITIES_KEY",
    "ibge/ibge_municipios_sp_test.json",
)

MONTH_KEYS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
GROUP_KEYS = ["state", "city", "ibge_city_code"]


def download_s3_file(bucket, key, local_path):
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read()

    with open(local_path, "wb") as f:
        f.write(content)

def load_trusted_records_from_s3(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    payload = json.loads(content)

    if not isinstance(payload, list):
        raise ValueError("Arquivo trusted invalido: esperado JSON array.")

    return payload


def build_refined_key():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_folder = datetime.now().strftime("%m-%Y")
    return f"{date_folder}/solar_data_refined_{timestamp}.json"


def calculate_seasons(monthly_data):
    return {
        "summer_avg": round((monthly_data.get("JAN", 0) + monthly_data.get("FEB", 0) + monthly_data.get("DEC", 0)) / 3, 1),
        "autumn_avg": round((monthly_data.get("MAR", 0) + monthly_data.get("APR", 0) + monthly_data.get("MAY", 0)) / 3, 1),
        "winter_avg": round((monthly_data.get("JUN", 0) + monthly_data.get("JUL", 0) + monthly_data.get("AUG", 0)) / 3, 1),
        "spring_avg": round((monthly_data.get("SEP", 0) + monthly_data.get("OCT", 0) + monthly_data.get("NOV", 0)) / 3, 1),
    }


def aggregate_records(valid_records):
    if not valid_records:
        return []

    grouped = {}

    for record in valid_records:
        missing_group_field = any(record.get(field) in (None, "") for field in GROUP_KEYS)
        if missing_group_field:
            continue

        group_key = tuple(record[field] for field in GROUP_KEYS)
        group = grouped.setdefault(
            group_key,
            {
                "state": record["state"],
                "city": record["city"],
                "ibge_city_code": record["ibge_city_code"],
                "ibge_city_name": record.get("ibge_city_name"),
                "ibge_state_name": record.get("ibge_state_name"),
                "ibge_state_acronym": record.get("ibge_state_acronym"),
                "points_count": 0,
                "lat_sum": 0.0,
                "lon_sum": 0.0,
                "annual_sum": 0.0,
                "month_sums": {month.lower() + "_avg": 0.0 for month in MONTH_KEYS},
                "season_sums": {
                    "summer_avg": 0.0,
                    "autumn_avg": 0.0,
                    "winter_avg": 0.0,
                    "spring_avg": 0.0,
                },
            },
        )

        group["points_count"] += 1
        group["lat_sum"] += float(record["lat"])
        group["lon_sum"] += float(record["lon"])
        group["annual_sum"] += float(record["annual"])

        for month in MONTH_KEYS:
            group["month_sums"][month.lower() + "_avg"] += float(record.get(month, 0.0))

        for season_key in group["season_sums"]:
            group["season_sums"][season_key] += float(record.get(season_key, 0.0))

    aggregated_records = []
    for group in grouped.values():
        points_count = group["points_count"]
        aggregated_records.append(
            {
                "state": group["state"],
                "city": group["city"],
                "ibge_city_code": group["ibge_city_code"],
                "ibge_city_name": group["ibge_city_name"],
                "ibge_state_name": group["ibge_state_name"],
                "ibge_state_acronym": group["ibge_state_acronym"],
                "points_count": points_count,
                "avg_lat": round(group["lat_sum"] / points_count, 1),
                "avg_lon": round(group["lon_sum"] / points_count, 1),
                "annual_avg": round(group["annual_sum"] / points_count, 1),
                **{
                    month_key: round(total / points_count, 1)
                    for month_key, total in group["month_sums"].items()
                },
                **{
                    season_key: round(total / points_count, 1)
                    for season_key, total in group["season_sums"].items()
                },
            }
        )

    return aggregated_records


def build_base_valid_records(trusted_records):
    valid_records = []

    for reading in trusted_records:
        monthly_data = reading.get("monthly_data", {})
        seasons = calculate_seasons(monthly_data)

        valid_records.append(
            {
                "id": reading["id"],
                "lat": float(reading["lat"]),
                "lon": float(reading["lon"]),
                "state": reading.get("state"),
                "city": None,
                "ibge_city_code": None,
                "ibge_city_name": None,
                "ibge_state_name": None,
                "ibge_state_acronym": None,
                "annual": round(float(reading["annual"]), 1),
                **{month: round(float(monthly_data.get(month, 0)), 1) for month in MONTH_KEYS},
                **seasons,
            }
        )

    return valid_records


def lambda_handler(event, context):
    processed_files = []

    for record in event.get("Records", []):
        source_bucket = record["s3"]["bucket"]["name"]
        source_key = unquote_plus(record["s3"]["object"]["key"])

        if source_bucket != TRUSTED_BUCKET:
            print(f"Ignorando bucket nao esperado: {source_bucket}")
            continue

        if not source_key.lower().endswith(".json"):
            print(f"Ignorando arquivo nao JSON: {source_key}")
            continue

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Processando: {source_key}")

        geojson_tmp_path = "/tmp/ibge_sp_municipios_geo_fixed.geojson"
        municipalities_tmp_path = "/tmp/ibge_municipios_sp_test.json"

        download_s3_file(SUPPORT_BUCKET, SUPPORT_IBGE_GEOJSON_KEY, geojson_tmp_path)
        download_s3_file(SUPPORT_BUCKET, SUPPORT_IBGE_MUNICIPALITIES_KEY, municipalities_tmp_path)

        resolver = MunicipalityResolver(
            geojson_path=geojson_tmp_path,
            municipalities_path=municipalities_tmp_path,
            cache_path="/tmp/municipality_lookup_sp.json",
)
        trusted_records = load_trusted_records_from_s3(source_bucket, source_key)
        valid_records = build_base_valid_records(trusted_records)
        aggregated_records = aggregate_records(valid_records)

        target_key = build_refined_key()
        s3.put_object(
            Bucket=REFINED_BUCKET,
            Key=target_key,
            Body=json.dumps(aggregated_records, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros lidos: {len(trusted_records)}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros preparados: {len(valid_records)}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros agregados: {len(aggregated_records)}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: s3://{REFINED_BUCKET}/{target_key}")

        processed_files.append(
            {
                "source_bucket": source_bucket,
                "source_key": source_key,
                "target_bucket": REFINED_BUCKET,
                "target_key": target_key,
                "records_read": len(trusted_records),
                "records_prepared": len(valid_records),
                "records_aggregated": len(aggregated_records),
            }
        )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "trusted_to_refined base lambda concluido",
                "processed_files": processed_files,
                "next_step": "incorporar municipality resolver",
            },
            ensure_ascii=False,
        ),
    }
