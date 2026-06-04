"""
run_analysis.py
Main pipeline entry point.

Usage:
    python pipeline/run_analysis.py \
        --question "How many schools are in Alameda county?" \
        --db california_schools \
        --dataset bird \
        --split dev

    python pipeline/run_analysis.py \
        --question "Who won the most races?" \
        --db formula_1 \
        --dataset bird \
        --split dev \
        --model ollama
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import schema_path, DEFAULT_MODEL


def get_model(model_name: str):
    if model_name == "ollama":
        from models.ollama_model import OllamaModel
        return OllamaModel()
    elif model_name == "openai":
        from models.openai_model import OpenAIModel
        return OpenAIModel()
    elif model_name == "anthropic":
        from models.anthropic_model import AnthropicModel
        return AnthropicModel()
    else:
        raise ValueError(f"Unknown model '{model_name}'. Choose: ollama | openai | anthropic")


def load_schema(dataset: str, db_name: str) -> dict:
    path = schema_path(dataset, db_name)
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    return json.loads(path.read_text())


def find_db_path(dataset: str, db_name: str) -> Path:
    base = Path("datasets") / dataset / "databases"
    matches = list(base.rglob(f"{db_name}.sqlite"))
    if not matches:
        raise FileNotFoundError(f"No SQLite file found for '{db_name}' under {base}")
    return matches[0]


def execute_sql(db_path: Path, sql: str) -> tuple[list, list]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(sql)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    conn.close()
    return columns, [list(r) for r in rows]


def print_results(columns: list, rows: list) -> None:
    if not rows:
        print("(no results)")
        return
    col_widths = [max(len(str(c)), max((len(str(r[i])) for r in rows), default=0))
                  for i, c in enumerate(columns)]
    header = " | ".join(str(c).ljust(w) for c, w in zip(columns, col_widths))
    print(header)
    print("-" * len(header))
    for row in rows[:50]:
        print(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
    if len(rows) > 50:
        print(f"... ({len(rows)} rows total, showing first 50)")


def run(question: str, dataset: str, db_name: str, split: str, model_name: str) -> None:
    print(f"\nQuestion : {question}")
    print(f"Database : {db_name} ({dataset}/{split})")
    print(f"Model    : {model_name}\n")

    schema = load_schema(dataset, db_name)
    model = get_model(model_name)

    print("Generating SQL...")
    sql = model.generate_sql(question, schema)
    print(f"\nSQL:\n{sql}\n")

    db_path = find_db_path(dataset, db_name)
    print("Executing...")
    columns, rows = execute_sql(db_path, sql)
    print(f"\nResults ({len(rows)} rows):")
    print_results(columns, rows)


def main():
    parser = argparse.ArgumentParser(description="NL2Report pipeline")
    parser.add_argument("--question", required=True, help="Natural language question")
    parser.add_argument("--db", required=True, help="Database name (e.g. california_schools)")
    parser.add_argument("--dataset", default="bird", help="Dataset (default: bird)")
    parser.add_argument("--split", default="", help="Split: train | dev (auto-detected if omitted)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model: ollama | openai | anthropic (default: ollama)")
    args = parser.parse_args()

    run(args.question, args.dataset, args.db, args.split, args.model)


if __name__ == "__main__":
    main()
