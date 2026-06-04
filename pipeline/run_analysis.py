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
        --question "What is the most popular beer style?" \
        --db craftbeer \
        --dataset bird \
        --split train
"""

import argparse
import json
import sqlite3
from pathlib import Path

from models.ollama_model import OllamaModel


def load_schema(dataset: str, db_name: str) -> dict:
    path = Path("datasets") / dataset / "schema_json" / f"{db_name}_schema.json"
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


def run(question: str, dataset: str, db_name: str, split: str) -> None:
    print(f"\nQuestion : {question}")
    print(f"Database : {db_name} ({dataset}/{split})\n")

    schema = load_schema(dataset, db_name)
    model = OllamaModel()

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
    parser.add_argument("--split", default=None, help="Split: train | dev (auto-detected if omitted)")
    args = parser.parse_args()

    run(args.question, args.dataset, args.db, args.split or "")


if __name__ == "__main__":
    main()
