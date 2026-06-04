"""
extract_schema.py
Reads any SQLite database and writes a schema JSON to the dataset's schema_json/ folder.

Usage:
    python pipeline/extract_schema.py --db datasets/bird/databases/dev/california_schools/california_schools.sqlite
    python pipeline/extract_schema.py --dataset bird          # extract all splits (train + dev)
    python pipeline/extract_schema.py --dataset bird --split dev   # extract one split only
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


def process_split(split_dir: Path, schema_dir: Path) -> None:
    db_files = sorted(split_dir.rglob("*.sqlite"))
    if not db_files:
        print(f"  No .sqlite files found under {split_dir}")
        return
    print(f"  [{split_dir.name}] {len(db_files)} database(s)")
    for db_path in db_files:
        process_db(db_path, schema_dir)


def process_dataset(dataset_name: str, split: str | None = None) -> None:
    base = Path("datasets") / dataset_name
    db_root = base / "databases"
    schema_dir = base / "schema_json"
    schema_dir.mkdir(parents=True, exist_ok=True)

    # Discover splits: subfolders of databases/ that contain .sqlite files
    splits = sorted(
        [d for d in db_root.iterdir() if d.is_dir() and list(d.rglob("*.sqlite"))]
    )

    if not splits:
        # Flat layout fallback (no train/dev subfolders)
        db_files = sorted(db_root.rglob("*.sqlite"))
        if not db_files:
            print(f"No .sqlite files found under {db_root}")
            return
        print(f"Found {len(db_files)} database(s) in {db_root}")
        for db_path in db_files:
            process_db(db_path, schema_dir)
        print("Done.")
        return

    if split:
        target = db_root / split
        if not target.exists():
            print(f"Split '{split}' not found under {db_root}. Available: {[d.name for d in splits]}")
            return
        process_split(target, schema_dir)
    else:
        for split_dir in splits:
            process_split(split_dir, schema_dir)

    print("Done.")


def main():
    parser = argparse.ArgumentParser(description="Extract SQLite schema to JSON")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--db", type=Path, help="Path to a single .sqlite file")
    group.add_argument("--dataset", type=str, help="Dataset name (bird | tpch | m5)")
    parser.add_argument("--split", type=str, default=None, help="Split to extract (e.g. train | dev). Omit to extract all splits.")
    args = parser.parse_args()

    if args.db:
        db_path: Path = args.db
        schema_dir = db_path.parent.parent.parent / "schema_json"
        schema_dir.mkdir(parents=True, exist_ok=True)
        process_db(db_path, schema_dir)
    else:
        process_dataset(args.dataset, args.split)


if __name__ == "__main__":
    main()
