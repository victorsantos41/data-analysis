import boto3
import json
import os
from datetime import datetime
from urllib.parse import unquote_plus


s3 = boto3.client("s3")

REFINED_BUCKET = os.getenv("REFINED_BUCKET", "solarway-refined")
SOCIOECONOMIC_BUCKET = os.getenv("SOCIOECONOMIC_BUCKET", "solarway-socioeconomic")
LAMBDA_ASSETS_DIR = os.getenv("LAMBDA_ASSETS_DIR", os.path.dirname(__file__))
SIDRA_SNAPSHOT_PATH = os.path.join(
    LAMBDA_ASSETS_DIR,
    os.getenv("SIDRA_SNAPSHOT_FILE", "sidra_snapshot.json"),
)
UNKNOWN_TEXT = "desconhecido"


def safe_text(value, default=UNKNOWN_TEXT):
    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def safe_float(value, default=None):
    if value in (None, "", "...", "..", "X", "-"):
        return default

    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def load_refined_records_from_s3(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    payload = json.loads(content)

    if not isinstance(payload, list):
        raise ValueError("Arquivo refined invalido: esperado JSON array.")

    return payload


def load_sidra_snapshot(snapshot_path):
    with open(snapshot_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise ValueError("Snapshot SIDRA invalido: esperado JSON object indexado por ibge_city_code.")

    return payload


def build_target_key():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_folder = datetime.now().strftime("%m-%Y")
    return f"incoming/{date_folder}/solar_data_socioeconomic_{timestamp}.json"


def is_aggregated_refined_file(file_name, records):
    if not file_name.startswith("solar_data_refined_") or not file_name.endswith(".json"):
        return False

    if "_meta_" in file_name or "_manifest_" in file_name or "_rejected_" in file_name:
        return False

    if not isinstance(records, list) or not records:
        return False

    first_record = records[0]
    required_keys = {
        "state",
        "city",
        "points_count",
        "avg_lat",
        "avg_lon",
        "annual_avg",
        "summer_avg",
        "autumn_avg",
        "winter_avg",
        "spring_avg",
        "ibge_city_code",
    }
    return isinstance(first_record, dict) and required_keys.issubset(first_record.keys())


def build_empty_socioeconomic_payload():
    return {
        "income_avg": None,
        "income_source": UNKNOWN_TEXT,
        "income_query": UNKNOWN_TEXT,
        "gdp_total": None,
        "population_total": None,
        "population_query": UNKNOWN_TEXT,
        "household_indicator_value": None,
        "household_indicator_source": UNKNOWN_TEXT,
        "household_indicator_query": UNKNOWN_TEXT,
        "households_total_for_internet": None,
        "households_with_internet": None,
        "urban_indicator_value": None,
        "urban_indicator_source": UNKNOWN_TEXT,
        "urban_indicator_query": UNKNOWN_TEXT,
        "households_total_for_urban": None,
        "urban_households": None,
        "sanitation_indicator_value": None,
        "sanitation_indicator_source": UNKNOWN_TEXT,
        "sanitation_indicator_query": UNKNOWN_TEXT,
        "households_total_for_sanitation": None,
        "households_with_sewage_network": None,
        "vulnerability_index": None,
        "vulnerability_source": "pendente",
    }


def build_socioeconomic_enrichment_from_snapshot(record, sidra_snapshot):
    ibge_city_code = record.get("ibge_city_code")
    if not ibge_city_code:
        return build_empty_socioeconomic_payload()

    snapshot_key = str(ibge_city_code)
    snapshot_data = sidra_snapshot.get(snapshot_key)
    if not isinstance(snapshot_data, dict):
        return build_empty_socioeconomic_payload()

    return {
        **build_empty_socioeconomic_payload(),
        **snapshot_data,
    }


SIDRA_SNAPSHOT = load_sidra_snapshot(SIDRA_SNAPSHOT_PATH)


def lambda_handler(event, context):
    processed_files = []

    for record in event.get("Records", []):
        source_bucket = record["s3"]["bucket"]["name"]
        source_key = unquote_plus(record["s3"]["object"]["key"])

        if source_bucket != REFINED_BUCKET:
            print(f"Ignorando bucket nao esperado: {source_bucket}")
            continue

        if not source_key.lower().endswith(".json"):
            print(f"Ignorando arquivo nao JSON: {source_key}")
            continue

        file_name = os.path.basename(source_key)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Processando: {source_key}")

        refined_records = load_refined_records_from_s3(source_bucket, source_key)
        if not is_aggregated_refined_file(file_name, refined_records):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Arquivo fora do schema refined agregado: {source_key}")
            continue

        enriched_records = []
        snapshot_match_count = 0
        snapshot_missing_count = 0

        for refined_record in refined_records:
            socioeconomic_data = build_socioeconomic_enrichment_from_snapshot(refined_record, SIDRA_SNAPSHOT)
            if socioeconomic_data["income_source"] != UNKNOWN_TEXT:
                snapshot_match_count += 1
            else:
                snapshot_missing_count += 1

            enriched_records.append(
                {
                    **refined_record,
                    **socioeconomic_data,
                    "socioeconomic_processed_at": datetime.now().isoformat(),
                    "socioeconomic_source_file": file_name,
                }
            )

        target_key = build_target_key()
        s3.put_object(
            Bucket=SOCIOECONOMIC_BUCKET,
            Key=target_key,
            Body=json.dumps(enriched_records, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros lidos: {len(refined_records)}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros enriquecidos: {len(enriched_records)}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Match snapshot: {snapshot_match_count}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sem dados no snapshot: {snapshot_missing_count}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: s3://{SOCIOECONOMIC_BUCKET}/{target_key}")

        processed_files.append(
            {
                "source_bucket": source_bucket,
                "source_key": source_key,
                "target_bucket": SOCIOECONOMIC_BUCKET,
                "target_key": target_key,
                "records_read": len(refined_records),
                "records_enriched": len(enriched_records),
                "snapshot_match_count": snapshot_match_count,
                "snapshot_missing_count": snapshot_missing_count,
            }
        )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "refined_to_socioeconomic lambda concluido",
                "processed_files": processed_files,
            },
            ensure_ascii=False,
        ),
    }
