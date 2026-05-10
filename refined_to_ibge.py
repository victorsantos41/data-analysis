import gzip
import json
import math
import os
import time
import unicodedata
import urllib.request
from datetime import datetime

from dotenv import load_dotenv
from etl_utils import append_processed_file, ensure_directory, load_processed_files, read_json_file, write_json_file
from location_cache import city_state_key

load_dotenv()

UNKNOWN_TEXT = "desconhecido"
STATE_NAME_TO_ACRONYM = {
    "acre": "AC",
    "alagoas": "AL",
    "amapa": "AP",
    "amazonas": "AM",
    "bahia": "BA",
    "ceara": "CE",
    "distrito federal": "DF",
    "espirito santo": "ES",
    "goias": "GO",
    "maranhao": "MA",
    "mato grosso": "MT",
    "mato grosso do sul": "MS",
    "minas gerais": "MG",
    "para": "PA",
    "paraiba": "PB",
    "parana": "PR",
    "pernambuco": "PE",
    "piaui": "PI",
    "rio de janeiro": "RJ",
    "rio grande do norte": "RN",
    "rio grande do sul": "RS",
    "rondonia": "RO",
    "roraima": "RR",
    "santa catarina": "SC",
    "sao paulo": "SP",
    "sergipe": "SE",
    "tocantins": "TO",
}


def safe_text(value, default=UNKNOWN_TEXT):
    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def has_real_value(value):
    if value is None:
        return False
    if isinstance(value, float):
        return not math.isnan(value)
    return True


def normalize_text(value):
    text = safe_text(value, default="")
    text = text.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def get_state_acronym(state_name):
    normalized_state = normalize_text(state_name)
    return STATE_NAME_TO_ACRONYM.get(normalized_state)


def read_json_response(response):
    raw_content = response.read()
    if not raw_content:
        return None

    content_encoding = response.headers.get("Content-Encoding", "").lower()
    if content_encoding == "gzip":
        raw_content = gzip.decompress(raw_content)

    return json.loads(raw_content.decode("utf-8"))


def fetch_municipalities_by_state(state_acronym):
    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{state_acronym}/municipios"
    try:
        time.sleep(0.3)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "SolarwayBusinessIBGE/1.0",
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
        )

        with urllib.request.urlopen(req) as response:
            if response.getcode() != 200:
                return []

            data = read_json_response(response)
            return data if isinstance(data, list) else []

    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Erro ao buscar municipios da UF {state_acronym}: {e}")
        return []


def fetch_ibge_city(city_name, state_name, state_cache):
    """
    Busca o municipio no servico de localidades do IBGE.
    A estrategia utilizada e consultar todos os municipios da UF
    e fazer o match localmente pelo nome normalizado do municipio.
    """
    normalized_city = normalize_text(city_name)
    normalized_state = normalize_text(state_name)

    if not normalized_city or not normalized_state:
        return None

    state_acronym = get_state_acronym(state_name)
    if not state_acronym:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] UF nao mapeada para: {state_name}")
        return None

    if state_acronym not in state_cache:
        state_cache[state_acronym] = fetch_municipalities_by_state(state_acronym)

    municipalities = state_cache[state_acronym]

    for item in municipalities:
        ibge_city_name = safe_text(item.get("nome"))
        if normalize_text(ibge_city_name) == normalized_city:
            return {
                "ibge_city_code": item.get("id"),
                "ibge_city_name": ibge_city_name,
                "ibge_state_acronym": state_acronym,
                "ibge_state_name": safe_text(state_name),
            }

    return None


def build_local_ibge_cache(ibge_path):
    local_cache = {}

    if not os.path.exists(ibge_path):
        return local_cache

    for root, _, files in os.walk(ibge_path):
        for file_name in files:
            if not file_name.startswith("solar_data_ibge_") or not file_name.endswith(".json"):
                continue

            records = read_json_file(os.path.join(root, file_name), default=[])
            if not isinstance(records, list):
                continue

            for record in records:
                if record.get("ibge_match_status") != "matched":
                    continue
                if not has_real_value(record.get("ibge_city_code")):
                    continue

                key = city_state_key(record.get("city"), record.get("state"))
                if key == "|":
                    continue

                local_cache[key] = {
                    "ibge_city_code": record.get("ibge_city_code"),
                    "ibge_city_name": record.get("ibge_city_name"),
                    "ibge_state_acronym": record.get("ibge_state_acronym"),
                    "ibge_state_name": record.get("ibge_state_name"),
                }

    return local_cache


def is_aggregated_refined_file(root, file_name):
    if not file_name.startswith("solar_data_refined_") or not file_name.endswith(".json"):
        return False

    if "_meta_" in file_name or "_manifest_" in file_name or "_rejected_" in file_name:
        return False

    file_path = os.path.join(root, file_name)
    records = read_json_file(file_path, default=[])
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
    }
    return isinstance(first_record, dict) and required_keys.issubset(first_record.keys())


def process_business_to_ibge():
    refined_path = os.getenv("REFINED_DATA_PATH", "data/refined")
    ibge_path = os.getenv("IBGE_DATA_PATH", "data/ibge")

    ensure_directory(ibge_path)
    local_ibge_cache = build_local_ibge_cache(ibge_path)

    for root, _, files in os.walk(refined_path):
        processed_log = os.path.join(root, ".processed_ibge")
        processed_files = load_processed_files(processed_log)

        refined_files = [
            f for f in files
            if is_aggregated_refined_file(root, f) and f not in processed_files
        ]

        if not refined_files:
            continue

        for file_name in refined_files:
            file_path = os.path.join(root, file_name)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Enriquecendo refined com IBGE: {file_name}")

            try:
                records = read_json_file(file_path, default=[])

                if not records:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Arquivo vazio: {file_name}")
                    append_processed_file(processed_log, file_name)
                    continue

                city_cache = {}
                state_cache = {}
                enriched_records = []
                matched_count = 0

                for record in records:
                    city = safe_text(record.get("city"))
                    state = safe_text(record.get("state"))
                    cache_key = (normalize_text(city), normalize_text(state))
                    local_key = city_state_key(city, state)

                    if has_real_value(record.get("ibge_city_code")):
                        city_cache[cache_key] = {
                            "ibge_city_code": record.get("ibge_city_code"),
                            "ibge_city_name": record.get("ibge_city_name"),
                            "ibge_state_acronym": record.get("ibge_state_acronym"),
                            "ibge_state_name": record.get("ibge_state_name"),
                        }
                    elif local_key in local_ibge_cache:
                        city_cache[cache_key] = local_ibge_cache[local_key]
                    elif cache_key not in city_cache:
                        city_cache[cache_key] = fetch_ibge_city(city, state, state_cache)

                    ibge_data = city_cache[cache_key]

                    enriched = {
                        **record,
                        "ibge_city_code": None,
                        "ibge_city_name": UNKNOWN_TEXT,
                        "ibge_state_name": UNKNOWN_TEXT,
                        "ibge_state_acronym": UNKNOWN_TEXT,
                        "ibge_match_status": "not_found",
                    }

                    if ibge_data and has_real_value(ibge_data.get("ibge_city_code")):
                        enriched.update(ibge_data)
                        enriched["ibge_match_status"] = "matched"
                        matched_count += 1

                    enriched_records.append(enriched)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                date_folder = os.path.basename(root)
                target_dir = os.path.join(ibge_path, date_folder)
                ensure_directory(target_dir)

                target_file = os.path.join(target_dir, f"solar_data_ibge_{timestamp}.json")
                write_json_file(target_file, enriched_records)

                append_processed_file(processed_log, file_name)

                print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros enriquecidos: {len(enriched_records)}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Matches IBGE: {matched_count}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: {target_file}")

            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Erro ao processar {file_name}: {e}")


if __name__ == "__main__":
    process_business_to_ibge()
