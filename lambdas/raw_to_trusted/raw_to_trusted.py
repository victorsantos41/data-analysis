import boto3
import csv
import json
import os
from datetime import datetime
from io import StringIO

s3 = boto3.client("s3")

RAW_BUCKET = os.getenv("RAW_BUCKET", "solarway-raw")
TRUSTED_BUCKET = os.getenv("TRUSTED_BUCKET", "solarway-trusted")

MONTH_KEYS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def safe_float(value):
    if value is None:
        return 0.0

    text = str(value).strip()
    if not text:
        return 0.0

    return round(float(text.replace(",", ".")), 1)


def build_target_key():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_folder = datetime.now().strftime("%m-%Y")
    return f"incoming/{date_folder}/solar_data_trusted_{timestamp}.json"


def process_csv_content(csv_content):
    reader = csv.DictReader(StringIO(csv_content), delimiter=";")
    deduplicated = {}

    for row in reader:
        if not row.get("ID"):
            continue

        row_id = int(row["ID"])
        deduplicated[row_id] = {
            "id": row_id,
            "state": row["UF"],
            "lon": float(row["LON"]),
            "lat": float(row["LAT"]),
            "annual": safe_float(row["ANNUAL"]),
            "monthly_data": {month: safe_float(row.get(month)) for month in MONTH_KEYS},
        }

    return list(deduplicated.values())


def lambda_handler(event, context):
    processed_files = []

    for record in event.get("Records", []):
        source_bucket = record["s3"]["bucket"]["name"]
        source_key = record["s3"]["object"]["key"]

        if source_bucket != RAW_BUCKET:
            print(f"Ignorando bucket nao esperado: {source_bucket}")
            continue

        if not source_key.lower().endswith(".csv"):
            print(f"Ignorando arquivo nao CSV: {source_key}")
            continue

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Processando: {source_key}")

        response = s3.get_object(Bucket=source_bucket, Key=source_key)
        csv_content = response["Body"].read().decode("utf-8-sig")

        records = process_csv_content(csv_content)

        target_key = build_target_key()

        s3.put_object(
            Bucket=TRUSTED_BUCKET,
            Key=target_key,
            Body=json.dumps(records, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json"
        )

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: s3://{TRUSTED_BUCKET}/{target_key}")

        processed_files.append({
            "source_bucket": source_bucket,
            "source_key": source_key,
            "target_bucket": TRUSTED_BUCKET,
            "target_key": target_key,
            "records_count": len(records)
        })

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "raw_to_trusted concluido",
            "processed_files": processed_files
        }, ensure_ascii=False)
    }