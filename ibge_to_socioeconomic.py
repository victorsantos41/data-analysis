import gzip
import json
import os
import urllib.request
from datetime import datetime
from time import sleep

from dotenv import load_dotenv

load_dotenv()

UNKNOWN_TEXT = "desconhecido"
SIDRA_QUERY_DELAY_SECONDS = 0.3

SIDRA_TABLES = {
    "gdp_municipal": {
        "table": 5938,
        "period": "2021",
        "description": "PIB municipal a precos correntes",
    },
    "population_total": {
        "table": 9923,
        "period": "2022",
        "description": "Populacao residente por situacao do domicilio",
    },
    "households_by_situation": {
        "table": 9922,
        "period": "2022",
        "description": "Domicilios por situacao urbana ou rural",
    },
    "internet_households": {
        "table": 9936,
        "period": "2022",
        "description": "Domicilios com conexao domiciliar a internet",
    },
    "sewage_households": {
        "table": 6805,
        "period": "2022",
        "description": "Domicilios por tipo de esgotamento sanitario",
    },
}


def ensure_directory(path):
    os.makedirs(path, exist_ok=True)


def load_processed_files(processed_log):
    if not os.path.exists(processed_log):
        return set()

    with open(processed_log, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def append_processed_file(processed_log, file_name):
    with open(processed_log, "a", encoding="utf-8") as f:
        f.write(f"{file_name}\n")


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


def read_json_response(response):
    raw_content = response.read()
    if not raw_content:
        return None

    content_encoding = response.headers.get("Content-Encoding", "").lower()
    if content_encoding == "gzip":
        raw_content = gzip.decompress(raw_content)

    return json.loads(raw_content.decode("utf-8"))


def fetch_sidra_values(query_path):
    base_url = "https://apisidra.ibge.gov.br/values"
    url = f"{base_url}{query_path}"

    try:
        sleep(SIDRA_QUERY_DELAY_SECONDS)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "SolarwaySocioeconomic/1.0",
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
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Erro SIDRA na consulta {query_path}: {e}")
        return []


def get_last_value(records):
    if not records or len(records) <= 1:
        return None

    for item in reversed(records[1:]):
        value = safe_float(item.get("V"))
        if value is not None:
            return value

    return None


def normalize_text(value):
    if value is None:
        return ""

    return " ".join(str(value).strip().lower().split())


def build_sidra_query(table_id, ibge_city_code, period):
    return f"/t/{table_id}/n6/{ibge_city_code}/p/{period}/v/allxp?formato=json"


def record_matches_terms(record, include_terms=None, exclude_terms=None):
    include_terms = include_terms or []
    exclude_terms = exclude_terms or []

    values = [normalize_text(v) for v in record.values() if isinstance(v, str)]
    haystack = " | ".join(values)

    if any(term not in haystack for term in include_terms):
        return False

    if any(term in haystack for term in exclude_terms):
        return False

    return True


def find_first_value(records, include_terms=None, exclude_terms=None):
    if not records or len(records) <= 1:
        return None

    include_terms = [normalize_text(term) for term in (include_terms or [])]
    exclude_terms = [normalize_text(term) for term in (exclude_terms or [])]

    for record in records[1:]:
        if record_matches_terms(record, include_terms, exclude_terms):
            value = safe_float(record.get("V"))
            if value is not None:
                return value

    return None


def calculate_percentage(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None

    return round((numerator / denominator) * 100, 2)


def fetch_gdp_and_population_proxy(ibge_city_code):
    gdp_query = build_sidra_query(
        SIDRA_TABLES["gdp_municipal"]["table"],
        ibge_city_code,
        SIDRA_TABLES["gdp_municipal"]["period"],
    )
    gdp_records = fetch_sidra_values(gdp_query)

    population_query = build_sidra_query(
        SIDRA_TABLES["population_total"]["table"],
        ibge_city_code,
        SIDRA_TABLES["population_total"]["period"],
    )
    population_records = fetch_sidra_values(population_query)

    gdp_total = find_first_value(
        gdp_records,
        include_terms=["produto interno bruto"],
        exclude_terms=["per capita", "participacao", "valor adicionado bruto", "impostos"],
    )
    population_total = find_first_value(
        population_records,
        include_terms=["populacao residente", "total"],
        exclude_terms=["urbana", "rural"],
    )

    gdp_per_capita_proxy = None
    if gdp_total is not None and population_total not in (None, 0):
        gdp_per_capita_proxy = round(gdp_total / population_total, 2)

    return {
        "income_avg": gdp_per_capita_proxy,
        "income_source": "sidra_gdp_population_proxy",
        "income_query": gdp_query,
        "gdp_total": gdp_total,
        "population_total": population_total,
        "population_query": population_query,
    }


def fetch_household_profile_indicator(ibge_city_code):
    query_path = build_sidra_query(
        SIDRA_TABLES["internet_households"]["table"],
        ibge_city_code,
        SIDRA_TABLES["internet_households"]["period"],
    )
    records = fetch_sidra_values(query_path)

    total_households = find_first_value(
        records,
        include_terms=["domicilios particulares permanentes ocupados", "total"],
        exclude_terms=["internet", "proprio", "alugado", "cedido"],
    )
    households_with_internet = find_first_value(
        records,
        include_terms=["domicilios particulares permanentes ocupados", "internet", "sim"],
    )

    return {
        "household_indicator_value": calculate_percentage(households_with_internet, total_households),
        "household_indicator_source": "sidra_internet_pct",
        "household_indicator_query": query_path,
        "households_total_for_internet": total_households,
        "households_with_internet": households_with_internet,
    }


def fetch_urban_indicator(ibge_city_code):
    query_path = build_sidra_query(
        SIDRA_TABLES["households_by_situation"]["table"],
        ibge_city_code,
        SIDRA_TABLES["households_by_situation"]["period"],
    )
    records = fetch_sidra_values(query_path)

    total_households = find_first_value(
        records,
        include_terms=["domicilios particulares permanentes ocupados", "total"],
        exclude_terms=["moradores", "media"],
    )
    urban_households = find_first_value(
        records,
        include_terms=["domicilios particulares permanentes ocupados", "urbana"],
        exclude_terms=["moradores", "media"],
    )

    return {
        "urban_indicator_value": calculate_percentage(urban_households, total_households),
        "urban_indicator_source": "sidra_urban_households_pct",
        "urban_indicator_query": query_path,
        "households_total_for_urban": total_households,
        "urban_households": urban_households,
    }


def fetch_sanitation_indicator(ibge_city_code):
    query_path = build_sidra_query(
        SIDRA_TABLES["sewage_households"]["table"],
        ibge_city_code,
        SIDRA_TABLES["sewage_households"]["period"],
    )
    records = fetch_sidra_values(query_path)

    total_households = find_first_value(
        records,
        include_terms=["domicilios particulares permanentes ocupados", "total"],
        exclude_terms=["rede geral", "fossa", "rio", "vala", "mar"],
    )
    adequate_sewage = find_first_value(
        records,
        include_terms=["domicilios particulares permanentes ocupados", "rede geral"],
    )

    return {
        "sanitation_indicator_value": calculate_percentage(adequate_sewage, total_households),
        "sanitation_indicator_source": "sidra_sewage_network_pct",
        "sanitation_indicator_query": query_path,
        "households_total_for_sanitation": total_households,
        "households_with_sewage_network": adequate_sewage,
    }


def build_socioeconomic_enrichment(record, indicator_cache):
    ibge_city_code = record.get("ibge_city_code")

    if not ibge_city_code:
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

    if ibge_city_code not in indicator_cache:
        indicator_cache[ibge_city_code] = {
            **fetch_gdp_and_population_proxy(ibge_city_code),
            **fetch_household_profile_indicator(ibge_city_code),
            **fetch_urban_indicator(ibge_city_code),
            **fetch_sanitation_indicator(ibge_city_code),
            "vulnerability_index": None,
            "vulnerability_source": "pendente",
        }

    return indicator_cache[ibge_city_code]


def process_ibge_to_socioeconomic():
    ibge_path = os.getenv("IBGE_DATA_PATH", "data/ibge")
    socioeconomic_path = os.getenv("SOCIOECONOMIC_DATA_PATH", "data/socioeconomic")

    ensure_directory(socioeconomic_path)

    for root, _, files in os.walk(ibge_path):
        processed_log = os.path.join(root, ".processed_socioeconomic")
        processed_files = load_processed_files(processed_log)

        ibge_files = [
            f for f in files
            if f.startswith("solar_data_ibge_") and f.endswith(".json") and f not in processed_files
        ]

        if not ibge_files:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Nenhum arquivo IBGE pendente em: {root}")
            continue

        for file_name in ibge_files:
            file_path = os.path.join(root, file_name)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Enriquecendo socioeconomic: {file_name}")

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    records = json.load(f)

                if not records:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Arquivo vazio: {file_name}")
                    append_processed_file(processed_log, file_name)
                    continue

                indicator_cache = {}
                enriched_records = []

                for record in records:
                    socioeconomic_data = build_socioeconomic_enrichment(record, indicator_cache)

                    enriched_record = {
                        **record,
                        **socioeconomic_data,
                        "socioeconomic_processed_at": datetime.now().isoformat(),
                        "socioeconomic_source_file": file_name,
                    }
                    enriched_records.append(enriched_record)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                date_folder = os.path.basename(root)
                target_dir = os.path.join(socioeconomic_path, date_folder)
                ensure_directory(target_dir)

                target_file = os.path.join(target_dir, f"solar_data_socioeconomic_{timestamp}.json")
                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(enriched_records, f, indent=4, ensure_ascii=False)

                append_processed_file(processed_log, file_name)

                print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros socioeconomic gerados: {len(enriched_records)}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: {target_file}")

            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Erro ao processar {file_name}: {e}")


if __name__ == "__main__":
    process_ibge_to_socioeconomic()
