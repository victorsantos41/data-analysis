import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv
from etl_utils import ensure_directory, load_processed_files, append_processed_file, write_json_file, iso_now

load_dotenv()

def process_raw_to_trusted():
    raw_path = os.getenv("RAW_DATA_PATH", "data/raw")
    trusted_path = os.getenv("TRUSTED_DATA_PATH", "data/trusted")
    
    # Garantir que o diretório trusted existe
    ensure_directory(trusted_path)

    # Listar arquivos CSV pendentes
    for root, dirs, files in os.walk(raw_path):
        processed_log = os.path.join(root, ".processed")
        processed_files = load_processed_files(processed_log)

        csv_files = [f for f in files if f.endswith(".csv") and f not in processed_files]
        
        for file_name in csv_files:
            file_path = os.path.join(root, file_name)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Processando: {file_name}")
            
            try:
                # Carregar CSV
                df = pd.read_csv(file_path, sep=';', encoding='utf-8-sig')
                
                # Deduplicação por ID
                df = df.drop_duplicates(subset=['ID'])
                
                # Tratamento de nulos e arredondamento (1 casa decimal)
                numeric_cols = ['ANNUAL', 'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
                for col in numeric_cols:
                    df[col] = df[col].fillna(0.0).round(1)
                
                # Padronização de nomes (Inglês)
                df = df.rename(columns={
                    'ID': 'id',
                    'UF': 'state',
                    'LON': 'lon',
                    'LAT': 'lat',
                    'ANNUAL': 'annual'
                })
                
                # Estruturar monthly_data como dicionário
                records = []
                for _, row in df.iterrows():
                    record = {
                        "id": int(row['id']),
                        "state": row['state'],
                        "lon": float(row['lon']),
                        "lat": float(row['lat']),
                        "annual": float(row['annual']),
                        "monthly_data": {m: float(row[m]) for m in ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']},
                    }
                    records.append(record)
                
                # Salvar em JSON com timestamp e pasta MM-YYYY
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                date_folder = datetime.now().strftime("%m-%Y")
                target_dir = os.path.join(trusted_path, date_folder)
                
                ensure_directory(target_dir)
                
                target_file = os.path.join(target_dir, f"solar_data_trusted_{timestamp}.json")
                meta_file = os.path.join(target_dir, f"solar_data_trusted_meta_{timestamp}.json")
                write_json_file(target_file, records)
                write_json_file(meta_file, {
                    "source_file": file_name,
                    "processed_at": iso_now(),
                    "records_count": len(records),
                    "schema_version": "trusted_v2",
                })
                
                # Marcar como processado
                append_processed_file(processed_log, file_name)
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Salvo em: {target_file}")
                
            except Exception as e:
                print(f"Erro ao processar {file_name}: {e}")

if __name__ == "__main__":
    process_raw_to_trusted()
