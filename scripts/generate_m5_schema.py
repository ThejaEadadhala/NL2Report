"""
generate_m5_schema.py
=====================
Reads datasets/m5/m5.sqlite and produces datasets/m5/schema_json/m5_schema.json.

Output format matches exactly what base_model.py format_schema() expects:
  schema["database"]  — database name
  schema["tables"]    — list of tables, each with:
      name, row_count, columns [{name, type, pk, description}], foreign_keys [{from, to_table, to_col}]

Usage (from project root):
    python scripts/generate_m5_schema.py
"""

import json
import sqlite3
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

SQLITE_PATH = Path("datasets/m5/m5.sqlite")
OUTPUT_PATH = Path("datasets/m5/schema_json/m5_schema.json")

# ── Human-readable column descriptions ────────────────────────────────────────

DESCRIPTIONS = {
    "sales": {
        "id":       "Unique item-store identifier (e.g. HOBBIES_1_001_CA_1_validation)",
        "item_id":  "Item identifier (e.g. HOBBIES_1_001)",
        "dept_id":  "Department identifier (HOBBIES_1, FOODS_3, HOUSEHOLD_2, etc.)",
        "cat_id":   "Category identifier (HOBBIES, FOODS, HOUSEHOLD)",
        "store_id": "Store identifier (CA_1, TX_2, WI_3, etc.)",
        "state_id": "State identifier (CA=California, TX=Texas, WI=Wisconsin)",
        "d":        "Day identifier (d_1 = 2011-01-29, d_1913 = 2016-06-19)",
        "sales":    "Number of units sold on this day at this store for this item",
    },
    "sales_evaluation": {
        "id":       "Unique item-store identifier",
        "item_id":  "Item identifier",
        "dept_id":  "Department identifier",
        "cat_id":   "Category identifier",
        "store_id": "Store identifier",
        "state_id": "State identifier",
        "d":        "Day identifier (d_1 = 2011-01-29, d_1941 = 2016-07-17, extends validation by 28 days)",
        "sales":    "Number of units sold on this day",
    },
    "calendar": {
        "date":         "Calendar date (YYYY-MM-DD)",
        "wm_yr_wk":     "Walmart week number (year + week, e.g. 11101)",
        "weekday":      "Day of week name (Saturday, Sunday, ...)",
        "wday":         "Day of week number (1=Saturday, 7=Friday)",
        "month":        "Month number (1–12)",
        "year":         "Calendar year (2011–2016)",
        "d":            "Day identifier matching the d column in sales table (d_1 .. d_1941)",
        "event_name_1": "Name of primary event on this date (e.g. SuperBowl, Christmas)",
        "event_type_1": "Type of primary event (Sporting, Cultural, National, Religious)",
        "event_name_2": "Name of secondary event on this date (if any)",
        "event_type_2": "Type of secondary event (if any)",
        "snap_CA":      "1 if SNAP benefits can be used in California on this date, else 0",
        "snap_TX":      "1 if SNAP benefits can be used in Texas on this date, else 0",
        "snap_WI":      "1 if SNAP benefits can be used in Wisconsin on this date, else 0",
    },
    "sell_prices": {
        "store_id":   "Store identifier",
        "item_id":    "Item identifier",
        "wm_yr_wk":   "Walmart week number — join with calendar.wm_yr_wk to get dates",
        "sell_price": "Selling price of the item at this store during this week (USD)",
    },
}

# ── Foreign keys ───────────────────────────────────────────────────────────────
# SQLite does not enforce FKs; we define them explicitly for LLM context.

FOREIGN_KEYS = {
    "sales":            [{"from": "d", "to_table": "calendar", "to_col": "d"}],
    "sales_evaluation": [{"from": "d", "to_table": "calendar", "to_col": "d"}],
    "calendar":         [],
    "sell_prices":      [{"from": "wm_yr_wk", "to_table": "calendar", "to_col": "wm_yr_wk"}],
}


def extract_schema(sqlite_path: Path) -> dict:
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    table_names = [row[0] for row in cursor.fetchall()]

    tables = []
    for table in table_names:
        cursor.execute(f"PRAGMA table_info('{table}');")
        columns = [
            {
                "name":        row[1],
                "type":        row[2] if row[2] else "TEXT",
                "pk":          bool(row[5]),
                "description": DESCRIPTIONS.get(table, {}).get(row[1], ""),
            }
            for row in cursor.fetchall()
        ]

        cursor.execute(f"SELECT COUNT(*) FROM '{table}';")
        row_count = cursor.fetchone()[0]

        tables.append({
            "name":         table,
            "row_count":    row_count,
            "columns":      columns,
            "foreign_keys": FOREIGN_KEYS.get(table, []),
        })

    conn.close()
    return {"database": "m5", "tables": tables}


def main() -> None:
    if not SQLITE_PATH.exists():
        print(f"ERROR: {SQLITE_PATH} not found. Run scripts/load_m5_sqlite.py first.")
        return

    print(f"\nReading: {SQLITE_PATH}")
    schema = extract_schema(SQLITE_PATH)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2))

    print(f"\nSchema summary:")
    for t in schema["tables"]:
        print(f"  {t['name']:<25} {t['row_count']:>12,} rows  "
              f"{len(t['columns'])} columns  {len(t['foreign_keys'])} FKs")

    print(f"\nOutput: {OUTPUT_PATH}")
    print("Done.\n")


if __name__ == "__main__":
    main()
