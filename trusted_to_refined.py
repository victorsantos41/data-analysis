import boto3
import json
import math
import os
from datetime import datetime
from urllib.parse import unquote_plus

s3 = boto3.client("s3")

TRUSTED_BUCKET = os.getenv("TRUSTED_BUCKET","solarway-trusted")
REFINED_BUCKET = os.getenv("REFINED_BUCKET","solarway-refined")
SUPPORT_BUCKET = os.getenv("SUPPORT_BUCKET","solarway-support")

SUPPORT_IBGE_GEOJSON_KEY = os.getenv(
    "SUPPORT_IBGE_GEOJSON_KEY",
    "ibge/ibge_sp_municipios_geo_fixed.geojson"
)

SUPPORT_IBGE_MUNICIPALITIES_KEY = os.getenv(
    "SUPPORT_IBGE_MUNICIPALITIES_KEY",
    "ibge/ibge_municipios_sp_test.json"
)

MONTH_KEYS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
UNKNOWN_TEXT = "desconhecido"

def download_s3_file(bucket,key,local_path):
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read()

    with open(local_path, "wb") as f:
        f.write(content)

def load_trusted_records_from_s3(bucket,s3):
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    return json.loads(content)

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

def lambda_handler(event,context):
    processed_files = []

    for record in event.get("Records", []):
        source_bucket = record["s3"]["bukcet"]["name"]
        source_key = record["s3"]["object"]["key"]

        if source_bucket != TRUSTED_BUCKET:
            print(f"Ignorando bucket nao esperado: {source_bucket}")
            continue

        if not source_key.lower().endswith(".json"):
            print(f"Ignorando arquivo nao JSON: {source_key}")
            continue

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Processando: {source_key}")