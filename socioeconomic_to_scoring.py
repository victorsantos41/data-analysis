import json
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

UNKNOWN_TEXT = "desconhecido"

SCORE_WEIGHTS = {
    "solar": 0.45,
    "income": 0.25,
    "household": 0.15,
    "urban": 0.10,
    "sanitation": 0.05,
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


def safe_float(value, default=None):
    if value in (None, "", "...", "..", "X", "-"):
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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

    scores = {
        "solar_score": solar_score,
        "income_score": income_score,
        "household_score": household_score,
        "urban_score": urban_score,
        "sanitation_score": sanitation_score,
    }

    solar_lead_score = weighted_score({
        "solar_score": solar_score,
        "income_score": income_score,
        "household_score": household_score,
        "urban_score": urban_score,
        "sanitation_score": sanitation_score,
    })

    return {
        **record,
        **scores,
        "solar_lead_score": solar_lead_score,
        "lead_priority": classify_priority(solar_lead_score),
        "scoring_weights": SCORE_WEIGHTS,
        "scoring_processed_at": datetime.now().isoformat(),
    }


def process_socioeconomic_to_scoring():
    socioeconomic_path = os.getenv("SOCIOECONOMIC_DATA_PATH", "data/socioeconomic")
    scoring_path = os.getenv("SCORING_DATA_PATH", "data/scoring")

    ensure_directory(scoring_path)

    for root, _, files in os.walk(socioeconomic_path):
        processed_log = os.path.join(root, ".processed_scoring")
        processed_files = load_processed_files(processed_log)

        socioeconomic_files = [
            f for f in files
            if f.startswith("solar_data_socioeconomic_") and f.endswith(".json") and f not in processed_files
        ]

        if not socioeconomic_files:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Nenhum arquivo socioeconomic pendente em: {root}")
            continue

        for file_name in socioeconomic_files:
            file_path = os.path.join(root, file_name)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Gerando scoring: {file_name}")

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    records = json.load(f)

                if not records:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Arquivo vazio: {file_name}")
                    append_processed_file(processed_log, file_name)
                    continue

                bounds = {
                    "annual_avg": calculate_bounds(records, "annual_avg"),
                    "income_avg": calculate_bounds(records, "income_avg"),
                    "household_indicator_value": calculate_bounds(records, "household_indicator_value"),
                    "urban_indicator_value": calculate_bounds(records, "urban_indicator_value"),
                    "sanitation_indicator_value": calculate_bounds(records, "sanitation_indicator_value"),
                }

                scored_records = [build_scored_record(record, bounds) for record in records]
                scored_records.sort(
                    key=lambda item: safe_float(item.get("solar_lead_score"), default=-1),
                    reverse=True,
                )

                for index, record in enumerate(scored_records, start=1):
                    record["lead_rank"] = index

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                date_folder = os.path.basename(root)
                target_dir = os.path.join(scoring_path, date_folder)
                ensure_directory(target_dir)

                target_file = os.path.join(target_dir, f"solar_data_scoring_{timestamp}.json")
                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(scored_records, f, indent=4, ensure_ascii=False)

                append_processed_file(processed_log, file_name)

                print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros scoring gerados: {len(scored_records)}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: {target_file}")

            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Erro ao processar {file_name}: {e}")


if __name__ == "__main__":
    process_socioeconomic_to_scoring()
