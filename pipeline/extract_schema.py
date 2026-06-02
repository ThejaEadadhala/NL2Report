"""
extract_schema.py
Reads any SQLite database and writes a schema JSON to the dataset's schema_json/ folder.

Usage:
    python pipeline/extract_schema.py --db datasets/bird/databases/california_schools/california_schools.sqlite
    python pipeline/extract_schema.py --dataset bird          # extract all DBs in that dataset
"""

import argparse
import json
import sqlite3
from pathlib import Path


def extract_schema(db_path: Path) -> dict:
    """Return a dict describing all tables and columns in the SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall()]

    schema = {"database": db_path.stem, "tables": []}

    for table in tables:
        cursor.execute(f"PRAGMA table_info('{table}');")
        columns = [
            {
                "cid": row[0],
                "name": row[1],
                "type": row[2],
                "notnull": bool(row[3]),
                "default": row[4],
                "pk": bool(row[5]),
            }
            for row in cursor.fetchall()
        ]

        cursor.execute(f"PRAGMA foreign_key_list('{table}');")
        foreign_keys = [
            {"from": row[3], "to_table": row[2], "to_col": row[4]}
            for row in cursor.fetchall()
        ]

        try:
            cursor.execute(f"SELECT COUNT(*) FROM '{table}';")
            row_count = cursor.fetchone()[0]
        except Exception:
            row_count = None

        schema["tables"].append(
            {
                "name": table,
                "columns": columns,
                "foreign_keys": foreign_keys,
                "row_count": row_count,
            }
        )

    conn.close()
    return schema


def process_db(db_path: Path, schema_json_dir: Path) -> Path:
    schema = extract_schema(db_path)
    out_path = schema_json_dir / f"{db_path.stem}_schema.json"
    out_path.write_text(json.dumps(schema, indent=2))
    print(f"  Wrote {out_path}")
    return out_path


def process_dataset(dataset_name: str) -> None:
    base = Path("datasets") / dataset_name
    db_root = base / "databases"
    schema_dir = base / "schema_json"
    schema_dir.mkdir(parents=True, exist_ok=True)

    db_files = sorted(db_root.rglob("*.sqlite"))
    if not db_files:
        print(f"No .sqlite files found under {db_root}")
        return

    print(f"Found {len(db_files)} database(s) in {db_root}")
    for db_path in db_files:
        process_db(db_path, schema_dir)
    print("Done.")


def main():
    parser = argparse.ArgumentParser(description="Extract SQLite schema to JSON")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--db", type=Path, help="Path to a single .sqlite file")
    group.add_argument("--dataset", type=str, help="Dataset name (bird | tpch | m5)")
    args = parser.parse_args()

    if args.db:
        db_path: Path = args.db
        schema_dir = db_path.parent.parent.parent / "schema_json"
        schema_dir.mkdir(parents=True, exist_ok=True)
        process_db(db_path, schema_dir)
    else:
        process_dataset(args.dataset)


if __name__ == "__main__":
    main()
