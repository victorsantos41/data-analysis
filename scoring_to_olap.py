import json
import os
from datetime import datetime

import boto3
import pymysql

s3 = boto3.client("s3")

SCORING_BUCKET = os.getenv("SCORING_BUCKET", "solarway-scoring-victor-santos")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")


def parse_generated_at(value):
    if not value:
        raise ValueError("summary.generated_at ausente")

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"summary.generated_at invalido: {value}") from exc


def load_scoring_payload_from_s3(source_bucket, source_key):
    response = s3.get_object(Bucket=source_bucket, Key=source_key)
    raw_content = response["Body"].read().decode("utf-8")
    return json.loads(raw_content)


def validate_scoring_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload de scoring deve ser um objeto JSON")

    summary = payload.get("summary")
    records = payload.get("records")

    if not isinstance(summary, dict):
        raise ValueError("payload de scoring sem bloco summary valido")

    if not isinstance(records, list):
        raise ValueError("payload de scoring sem bloco records valido")

    generated_at = parse_generated_at(summary.get("generated_at"))
    return summary, records, generated_at


def get_mysql_connection():
    missing = [
        name
        for name, value in [
            ("DB_HOST", DB_HOST),
            ("DB_NAME", DB_NAME),
            ("DB_USER", DB_USER),
            ("DB_PASSWORD", DB_PASSWORD),
        ]
        if not value
    ]

    if missing:
        raise ValueError(
            f"Variaveis de ambiente ausentes para MySQL: {', '.join(missing)}"
        )

    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def upsert_scoring_run(cursor, source_bucket, source_key, summary, generated_at):
    top_lead_region = summary.get("top_lead_region") or {}
    top_solar_region = summary.get("top_solar_region") or {}

    cursor.execute(
        """
        INSERT INTO scoring_run (
            source_bucket,
            source_key,
            source_file,
            generated_at,
            total_regions,
            top_lead_city,
            top_lead_state,
            top_lead_ibge_city_code,
            top_solar_city,
            top_solar_state,
            top_solar_ibge_city_code,
            ingested_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            source_bucket = VALUES(source_bucket),
            source_file = VALUES(source_file),
            generated_at = VALUES(generated_at),
            total_regions = VALUES(total_regions),
            top_lead_city = VALUES(top_lead_city),
            top_lead_state = VALUES(top_lead_state),
            top_lead_ibge_city_code = VALUES(top_lead_ibge_city_code),
            top_solar_city = VALUES(top_solar_city),
            top_solar_state = VALUES(top_solar_state),
            top_solar_ibge_city_code = VALUES(top_solar_ibge_city_code),
            ingested_at = NOW(),
            id_run = LAST_INSERT_ID(id_run)
        """,
        (
            source_bucket,
            source_key,
            summary.get("source_file"),
            generated_at,
            summary.get("total_regions"),
            top_lead_region.get("city"),
            top_lead_region.get("state"),
            top_lead_region.get("ibge_city_code"),
            top_solar_region.get("city"),
            top_solar_region.get("state"),
            top_solar_region.get("ibge_city_code"),
        ),
    )

    return cursor.lastrowid


def delete_existing_fact_rows(cursor, source_key):
    cursor.execute(
        "DELETE FROM fact_scoring_city WHERE source_key = %s",
        (source_key,),
    )


def insert_fact_rows(
    cursor,
    records,
    run_id,
    generated_at,
    source_bucket,
    source_key,
):
    insert_sql = """
        INSERT INTO fact_scoring_city (
            fk_run,
            state,
            city,
            ibge_city_code,
            lead_rank,
            lead_priority,
            points_count,
            avg_lat,
            avg_lon,
            annual_avg,
            income_avg,
            household_indicator_value,
            urban_indicator_value,
            sanitation_indicator_value,
            solar_score,
            income_score,
            household_score,
            urban_score,
            sanitation_score,
            solar_lead_score,
            generated_at,
            source_bucket,
            source_key,
            ingested_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, NOW()
        )
    """

    rows = []
    for record in records:
        rows.append(
            (
                run_id,
                record.get("state"),
                record.get("city"),
                record.get("ibge_city_code"),
                record.get("lead_rank"),
                record.get("lead_priority"),
                record.get("points_count"),
                record.get("avg_lat"),
                record.get("avg_lon"),
                record.get("annual_avg"),
                record.get("income_avg"),
                record.get("household_indicator_value"),
                record.get("urban_indicator_value"),
                record.get("sanitation_indicator_value"),
                record.get("solar_score"),
                record.get("income_score"),
                record.get("household_score"),
                record.get("urban_score"),
                record.get("sanitation_score"),
                record.get("solar_lead_score"),
                generated_at,
                source_bucket,
                source_key,
            )
        )

    if rows:
        cursor.executemany(insert_sql, rows)

    return len(rows)


def lambda_handler(event, context):
    processed_files = []

    for record in event.get("Records", []):
        source_bucket = record["s3"]["bucket"]["name"]
        source_key = record["s3"]["object"]["key"]

        if source_bucket != SCORING_BUCKET:
            print(f"Ignorando bucket nao esperado: {source_bucket}")
            continue

        if not source_key.lower().endswith(".json"):
            print(f"Ignorando arquivo nao JSON: {source_key}")
            continue

        connection = None
        cursor = None

        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Processando: {source_key}")

            payload = load_scoring_payload_from_s3(source_bucket, source_key)
            summary, records, generated_at = validate_scoring_payload(payload)

            connection = get_mysql_connection()
            cursor = connection.cursor()

            run_id = upsert_scoring_run(
                cursor,
                source_bucket,
                source_key,
                summary,
                generated_at,
            )
            delete_existing_fact_rows(cursor, source_key)
            inserted_count = insert_fact_rows(
                cursor,
                records,
                run_id,
                generated_at,
                source_bucket,
                source_key,
            )

            connection.commit()

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"Persistido source_key={source_key} run_id={run_id} registros={inserted_count}"
            )

            processed_files.append(
                {
                    "source_bucket": source_bucket,
                    "source_key": source_key,
                    "run_id": run_id,
                    "records_count": inserted_count,
                }
            )
        except Exception as exc:
            if connection:
                connection.rollback()

            print(f"Erro ao processar source_key={source_key}: {exc}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "scoring_to_olap concluido",
                "processed_files": processed_files,
            },
            ensure_ascii=False,
        ),
    }
