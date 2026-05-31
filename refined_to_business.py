import json
import os
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

GROUP_KEYS = ["state", "city", "suburb", "postcode"]
MONTH_COLUMNS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
SEASON_COLUMNS = ["summer_avg", "autumn_avg", "winter_avg", "spring_avg"]


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


def process_refined_to_business():
    refined_path = os.getenv("REFINED_DATA_PATH", "data/refined")
    business_path = os.getenv("BUSINESS_DATA_PATH", "data/business")

    ensure_directory(business_path)

    for root, _, files in os.walk(refined_path):
        processed_log = os.path.join(root, ".processed_business")
        processed_files = load_processed_files(processed_log)

        refined_files = [
            f for f in files
            if f.startswith("solar_data_refined_") and f.endswith(".json") and f not in processed_files
        ]

        if not refined_files:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Nenhum refined pendente em: {root}")
            continue

        for file_name in refined_files:
            file_path = os.path.join(root, file_name)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Processando business: {file_name}")

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    records = json.load(f)

                if not records:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Arquivo vazio: {file_name}")
                    append_processed_file(processed_log, file_name)
                    continue

                df = pd.DataFrame(records)

                required_columns = GROUP_KEYS + ["id", "lat", "lon", "annual", *MONTH_COLUMNS, *SEASON_COLUMNS]
                missing_columns = [col for col in required_columns if col not in df.columns]
                if missing_columns:
                    raise ValueError(f"Colunas ausentes no refined: {missing_columns}")

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
                    )
                    .reset_index()
                )

                numeric_columns = [
                    "avg_lat", "avg_lon", "annual_avg",
                    "jan_avg", "feb_avg", "mar_avg", "apr_avg", "may_avg", "jun_avg",
                    "jul_avg", "aug_avg", "sep_avg", "oct_avg", "nov_avg", "dec_avg",
                    "summer_avg", "autumn_avg", "winter_avg", "spring_avg"
                ]

                for col in numeric_columns:
                    aggregated[col] = aggregated[col].round(1)

                aggregated["source_file"] = file_name
                aggregated["processed_at"] = datetime.now().isoformat()

                result = aggregated.to_dict(orient="records")

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                date_folder = os.path.basename(root)
                target_dir = os.path.join(business_path, date_folder)
                ensure_directory(target_dir)

                target_file = os.path.join(
                    target_dir,
                    f"solar_data_business_{timestamp}.json"
                )

                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=4, ensure_ascii=False)

                append_processed_file(processed_log, file_name)

                print(f"[{datetime.now().strftime('%H:%M:%S')}] Registros business gerados: {len(result)}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: {target_file}")

            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Erro ao processar {file_name}: {e}")


if __name__ == "__main__":
    process_refined_to_business()