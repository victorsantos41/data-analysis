import argparse
import gzip
import json
import os
import urllib.request
from datetime import datetime
from time import sleep


UNKNOWN_TEXT = "desconhecido"
SIDRA_QUERY_DELAY_SECONDS = 0.3

SIDRA_TABLES = {
    "gdp_municipal": {
        "table": 5938,
        "period": "2021",
    },
    "population_total": {
        "table": 9923,
        "period": "2022",
    },
    "households_by_situation": {
        "table": 9922,
        "period": "2022",
    },
    "internet_households": {
        "table": 9936,
        "period": "2022",
    },
    "sewage_households": {
        "table": 6805,
        "period": "2022",
    },
}


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
                "User-Agent": "SolarwaySocioeconomicSnapshot/1.0",
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


def build_snapshot_entry(ibge_city_code):
    return {
        **fetch_gdp_and_population_proxy(ibge_city_code),
        **fetch_household_profile_indicator(ibge_city_code),
        **fetch_urban_indicator(ibge_city_code),
        **fetch_sanitation_indicator(ibge_city_code),
        "vulnerability_index": None,
        "vulnerability_source": "pendente",
    }


def load_refined_records(refined_file_path):
    with open(refined_file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, list):
        raise ValueError("Arquivo refined invalido: esperado JSON array.")

    return payload


def extract_ibge_city_codes(records):
    codes = set()
    for record in records:
        code = record.get("ibge_city_code")
        if code not in (None, ""):
            codes.add(str(code))
    return sorted(codes)


def write_snapshot(output_path, snapshot):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=4, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Gera snapshot SIDRA local para a Lambda refined_to_socioeconomic.")
    parser.add_argument("refined_file", help="Caminho do arquivo solar_data_refined_*.json")
    parser.add_argument(
        "--output",
        default="sidra_snapshot.json",
        help="Caminho de saida do snapshot JSON",
    )
    args = parser.parse_args()

    records = load_refined_records(args.refined_file)
    city_codes = extract_ibge_city_codes(records)
    if not city_codes:
        raise ValueError("Nenhum ibge_city_code encontrado no arquivo refined.")

    snapshot = {}
    for code in city_codes:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Gerando snapshot SIDRA para municipio {code}")
        snapshot[code] = build_snapshot_entry(code)

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    write_snapshot(args.output, snapshot)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Snapshot SIDRA salvo em: {args.output}")


if __name__ == "__main__":
    main()
