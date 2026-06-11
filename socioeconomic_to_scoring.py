import boto3
import json
import os
from datetime import datetime
from urllib.parse import unquote_plus


s3 = boto3.client("s3")

SOCIOECONOMIC_BUCKET = os.getenv("SOCIOECONOMIC_BUCKET", "solarway-socioeconomic-victor-santos")
SCORING_BUCKET = os.getenv("SCORING_BUCKET", "solarway-scoring-victor-santos")
UNKNOWN_TEXT = "desconhecido"

SCORE_WEIGHTS = {
    "solar": 0.45,
    "income": 0.25,
    "household": 0.15,
    "urban": 0.10,
    "sanitation": 0.05,
}

SUMMARY_RECORD_FIELDS = [
    "lead_rank",
    "state",
    "city",
    "ibge_city_code",
    "points_count",
    "avg_lat",
    "avg_lon",
    "annual_avg",
    "income_avg",
    "household_indicator_value",
    "urban_indicator_value",
    "sanitation_indicator_value",
    "solar_score",
    "income_score",
    "household_score",
    "urban_score",
    "sanitation_score",
    "solar_lead_score",
    "lead_priority",
]


def safe_float(value, default=None):
    if value in (None, "", "...", "..", "X", "-"):
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_socioeconomic_records_from_s3(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    payload = json.loads(content)

    if not isinstance(payload, list):
        raise ValueError("Arquivo socioeconomic invalido: esperado JSON array.")

    return payload


def build_target_key():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_folder = datetime.now().strftime("%m-%Y")
    return f"{date_folder}/solar_data_scoring_{timestamp}.json"


def is_valid_socioeconomic_record(record):
    required_keys = {
        "state",
        "city",
        "ibge_city_code",
        "annual_avg",
        "income_avg",
        "household_indicator_value",
        "urban_indicator_value",
        "sanitation_indicator_value",
    }
    return isinstance(record, dict) and required_keys.issubset(record.keys())


def calculate_bounds(records, field_name):
    values = [safe_float(record.get(field_name)) for record in records]
    values = [value for value in values if value is not None]

    if not values:
        return None, None

    return min(values), max(values)


def normalize_score(value, min_value, max_value):
    if value is None or min_value is None or max_value is None:
        return None

    if max_value == min_value:
        return 100.0

    return round(((value - min_value) / (max_value - min_value)) * 100, 2)


def weighted_score(scored_values):
    total = 0.0
    total_weight = 0.0

    for key, weight in SCORE_WEIGHTS.items():
        value = scored_values.get(f"{key}_score")
        if value is None:
            continue

        total += value * weight
        total_weight += weight

    if total_weight == 0:
        return None

    return round(total / total_weight, 2)


def classify_priority(score):
    if score is None:
        return UNKNOWN_TEXT
    if score >= 80:
        return "alta"
    if score >= 60:
        return "media_alta"
    if score >= 40:
        return "media"
    if score >= 20:
        return "media_baixa"
    return "baixa"


def build_scored_record(record, bounds):
    annual_avg = safe_float(record.get("annual_avg"))
    income_avg = safe_float(record.get("income_avg"))
    household_indicator_value = safe_float(record.get("household_indicator_value"))
    urban_indicator_value = safe_float(record.get("urban_indicator_value"))
    sanitation_indicator_value = safe_float(record.get("sanitation_indicator_value"))

    solar_score = normalize_score(annual_avg, *bounds["annual_avg"])
    income_score = normalize_score(income_avg, *bounds["income_avg"])
    household_score = normalize_score(household_indicator_value, *bounds["household_indicator_value"])
    urban_score = normalize_score(urban_indicator_value, *bounds["urban_indicator_value"])
    sanitation_score = normalize_score(sanitation_indicator_value, *bounds["sanitation_indicator_value"])

    solar_lead_score = weighted_score({
        "solar_score": solar_score,
        "income_score": income_score,
        "household_score": household_score,
        "urban_score": urban_score,
        "sanitation_score": sanitation_score,
    })

    return {
        "state": record.get("state"),
        "city": record.get("city"),
        "ibge_city_code": record.get("ibge_city_code"),
        "points_count": record.get("points_count"),
        "avg_lat": record.get("avg_lat"),
        "avg_lon": record.get("avg_lon"),
        "annual_avg": annual_avg,
        "income_avg": income_avg,
        "household_indicator_value": household_indicator_value,
        "urban_indicator_value": urban_indicator_value,
        "sanitation_indicator_value": sanitation_indicator_value,
        "solar_score": solar_score,
        "income_score": income_score,
        "household_score": household_score,
        "urban_score": urban_score,
        "sanitation_score": sanitation_score,
        "solar_lead_score": solar_lead_score,
        "lead_priority": classify_priority(solar_lead_score),
    }


def build_summary_record(record):
    return {field: record.get(field) for field in SUMMARY_RECORD_FIELDS}


def build_summary(scored_records, source_file):
    top_lead_region = build_summary_record(scored_records[0]) if scored_records else None
    top_solar_record = max(
        scored_records,
        key=lambda item: safe_float(item.get("annual_avg"), default=-1),
        default=None,
    )
    top_solar_region = build_summary_record(top_solar_record) if top_solar_record else None

    return {
        "total_regions": len(scored_records),
        "top_lead_region": top_lead_region,
        "top_solar_region": top_solar_region,
        "generated_at": datetime.now().isoformat(),
        "source_file": source_file,
    }


def lambda_handler(event, context):
    processed_files = []

    for record in event.get("Records", []):
        source_bucket = record["s3"]["bucket"]["name"]
        source_key = unquote_plus(record["s3"]["object"]["key"])

        if source_bucket != SOCIOECONOMIC_BUCKET:
            print(f"Ignorando bucket nao esperado: {source_bucket}")
            continue

        if not source_key.lower().endswith(".json"):
            print(f"Ignorando arquivo nao JSON: {source_key}")
            continue

        file_name = os.path.basename(source_key)
        if not file_name.startswith("solar_data_socioeconomic_"):
            print(f"Ignorando arquivo fora do padrao socioeconomic: {source_key}")
            continue

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Processando: {source_key}")
        records = load_socioeconomic_records_from_s3(source_bucket, source_key)

        valid_records = [record for record in records if is_valid_socioeconomic_record(record)]
        if not valid_records:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Nenhum registro valido encontrado em: {source_key}")
            continue

        bounds = {
            "annual_avg": calculate_bounds(valid_records, "annual_avg"),
            "income_avg": calculate_bounds(valid_records, "income_avg"),
            "household_indicator_value": calculate_bounds(valid_records, "household_indicator_value"),
            "urban_indicator_value": calculate_bounds(valid_records, "urban_indicator_value"),
            "sanitation_indicator_value": calculate_bounds(valid_records, "sanitation_indicator_value"),
        }

        scored_records = [build_scored_record(record, bounds) for record in valid_records]
        scored_records.sort(
            key=lambda item: safe_float(item.get("solar_lead_score"), default=-1),
            reverse=True,
        )

        for index, scored_record in enumerate(scored_records, start=1):
            scored_record["lead_rank"] = index

        payload = {
            "summary": build_summary(scored_records, file_name),
            "records": scored_records,
        }

        target_key = build_target_key()
        s3.put_object(
            Bucket=SCORING_BUCKET,
            Key=target_key,
            Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros lidos: {len(records)}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros validos: {len(valid_records)}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros ranqueados: {len(scored_records)}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: s3://{SCORING_BUCKET}/{target_key}")

        processed_files.append(
            {
                "source_bucket": source_bucket,
                "source_key": source_key,
                "target_bucket": SCORING_BUCKET,
                "target_key": target_key,
                "records_read": len(records),
                "records_valid": len(valid_records),
                "records_ranked": len(scored_records),
            }
        )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "socioeconomic_to_scoring lambda concluido",
                "processed_files": processed_files,
            },
            ensure_ascii=False,
        ),
    }
