import json
import os
from datetime import datetime


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


def read_json_file(path, default=None):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_file(path, payload):
    ensure_directory(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


def iso_now():
    return datetime.now().isoformat()


def append_ai_journal_entry(journal_path, title, text):
    ensure_directory(os.path.dirname(journal_path) or ".")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(journal_path, "a", encoding="utf-8") as f:
        if os.path.getsize(journal_path) > 0:
            f.write("\n")
        f.write(f"## {timestamp} - {title}\n")
        f.write(f"{text.strip()}\n")
