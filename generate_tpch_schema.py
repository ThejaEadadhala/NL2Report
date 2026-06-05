"""
generate_tpch_schema.py
=======================
Reads datasets/tpch/tpch.sqlite and produces datasets/tpch/schema_json/tpch_schema.json.

The output format matches exactly what base_model.py format_schema() expects:
  schema["database"]  — database name
  schema["tables"]    — list of tables, each with:
      name, row_count, columns [{name, type, pk, description}], foreign_keys [{from, to_table, to_col}]

Usage:
    python generate_tpch_schema.py
"""

import json
import sqlite3
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

SQLITE_PATH = Path("datasets/tpch/tpch.sqlite")
OUTPUT_PATH = Path("datasets/tpch/schema_json/tpch_schema.json")

# ── Human-readable column descriptions ────────────────────────────────────────
# Keyed by table name → column name → description string.

DESCRIPTIONS = {
    "region": {
        "r_regionkey": "Unique region identifier (0–4)",
        "r_name":      "Region name (AFRICA, AMERICA, ASIA, EUROPE, MIDDLE EAST)",
        "r_comment":   "Miscellaneous comment",
    },
    "nation": {
        "n_nationkey": "Unique nation identifier (0–24)",
        "n_name":      "Nation name (e.g., GERMANY, FRANCE, BRAZIL)",
        "n_regionkey": "FK — region this nation belongs to",
        "n_comment":   "Miscellaneous comment",
    },
    "supplier": {
        "s_suppkey":   "Unique supplier identifier",
        "s_name":      "Supplier name (e.g., Supplier#000000001)",
        "s_address":   "Supplier mailing address",
        "s_nationkey": "FK — nation where supplier is located",
        "s_phone":     "Supplier contact phone number",
        "s_acctbal":   "Supplier account balance",
        "s_comment":   "Miscellaneous comment",
    },
    "part": {
        "p_partkey":     "Unique part identifier",
        "p_name":        "Part name (descriptive phrase)",
        "p_mfgr":        "Manufacturer (e.g., Manufacturer#1)",
        "p_brand":       "Brand name (e.g., Brand#13)",
        "p_type":        "Part type description (e.g., SMALL BURNISHED COPPER)",
        "p_size":        "Part size (integer, 1–50)",
        "p_container":   "Container type (e.g., SM BOX, LG DRUM, JUMBO BAG)",
        "p_retailprice": "Retail price of the part",
        "p_comment":     "Miscellaneous comment",
    },
    "partsupp": {
        "ps_partkey":    "FK — part supplied",
        "ps_suppkey":    "FK — supplier providing the part",
        "ps_availqty":   "Available quantity in stock for this supplier-part pair",
        "ps_supplycost": "Cost to procure one unit from this supplier",
        "ps_comment":    "Miscellaneous comment",
    },
    "customer": {
        "c_custkey":    "Unique customer identifier",
        "c_name":       "Customer name (e.g., Customer#000000001)",
        "c_address":    "Customer mailing address",
        "c_nationkey":  "FK — nation where customer is located",
        "c_phone":      "Customer contact phone number",
        "c_acctbal":    "Customer account balance (negative means outstanding debt)",
        "c_mktsegment": "Market segment (AUTOMOBILE, BUILDING, FURNITURE, HOUSEHOLD, MACHINERY)",
        "c_comment":    "Miscellaneous comment",
        "c_has_debt":   "Derived — 1 if c_acctbal < 0 (customer has debt), else 0",
    },
    "orders": {
        "o_orderkey":      "Unique order identifier",
        "o_custkey":       "FK — customer who placed the order",
        "o_orderstatus":   "Order status: F=fully fulfilled, O=open/pending, P=partially fulfilled",
        "o_totalprice":    "Total monetary value of the order",
        "o_orderdate":     "Date the order was placed",
        "o_orderpriority": "Order priority level (1-URGENT, 2-HIGH, 3-MEDIUM, 4-NOT SPECIFIED, 5-LOW)",
        "o_clerk":         "Clerk responsible for the order (e.g., Clerk#000000001)",
        "o_shippriority":  "Shipping priority flag (0 = normal)",
        "o_comment":       "Miscellaneous comment",
        "o_year":          "Derived — calendar year extracted from o_orderdate",
        "o_month":         "Derived — calendar month (1–12) extracted from o_orderdate",
        "o_quarter":       "Derived — calendar quarter (1–4) extracted from o_orderdate",
    },
    "lineitem": {
        "l_orderkey":    "FK — order this line item belongs to",
        "l_partkey":     "FK — part ordered (also FK to partsupp via l_suppkey)",
        "l_suppkey":     "FK — supplier fulfilling this line item",
        "l_linenumber":  "Line number within the order (1-based)",
        "l_quantity":    "Quantity of parts ordered on this line",
        "l_extendedprice": "Base price for this line (quantity × part retail price, before discounts/tax)",
        "l_discount":    "Discount fraction applied to extended price (0.00–0.10)",
        "l_tax":         "Tax fraction applied after discount (0.00–0.08)",
        "l_returnflag":  "Return status: R=returned, A=accepted return, N=not returned",
        "l_linestatus":  "Line status: O=open (order not fulfilled), F=fulfilled",
        "l_shipdate":    "Date the item was shipped",
        "l_commitdate":  "Committed delivery date agreed with customer",
        "l_receiptdate": "Date the item was actually received by the customer",
        "l_shipinstruct":"Shipping instructions (DELIVER IN PERSON, COLLECT COD, NONE, TAKE BACK RETURN)",
        "l_shipmode":    "Shipping mode (AIR, FOB, MAIL, RAIL, REG AIR, SHIP, TRUCK)",
        "l_comment":     "Miscellaneous comment",
        "l_net_revenue": "Derived — net revenue: l_extendedprice × (1 - l_discount) × (1 + l_tax)",
        "l_ship_year":   "Derived — calendar year extracted from l_shipdate",
        "l_ship_month":  "Derived — calendar month (1–12) extracted from l_shipdate",
    },
}

# ── Known TPC-H foreign keys ───────────────────────────────────────────────────
# SQLite does not enforce FKs by default; we define them explicitly here
# so the schema JSON is useful for LLM prompting.

FOREIGN_KEYS = {
    "nation":   [{"from": "n_regionkey",  "to_table": "region",   "to_col": "r_regionkey"}],
    "supplier": [{"from": "s_nationkey",  "to_table": "nation",   "to_col": "n_nationkey"}],
    "customer": [{"from": "c_nationkey",  "to_table": "nation",   "to_col": "n_nationkey"}],
    "partsupp": [
        {"from": "ps_partkey", "to_table": "part",     "to_col": "p_partkey"},
        {"from": "ps_suppkey", "to_table": "supplier", "to_col": "s_suppkey"},
    ],
    "orders":   [{"from": "o_custkey",    "to_table": "customer", "to_col": "c_custkey"}],
    "lineitem": [
        {"from": "l_orderkey", "to_table": "orders",   "to_col": "o_orderkey"},
        {"from": "l_partkey",  "to_table": "part",     "to_col": "p_partkey"},
        {"from": "l_suppkey",  "to_table": "supplier", "to_col": "s_suppkey"},
    ],
    "region":   [],
    "part":     [],
}


def extract_schema(sqlite_path: Path) -> dict:
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    table_names = [row[0] for row in cursor.fetchall()]

    tables = []
    for table in table_names:
        # Columns
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

        # Row count
        cursor.execute(f"SELECT COUNT(*) FROM '{table}';")
        row_count = cursor.fetchone()[0]

        tables.append({
            "name":         table,
            "row_count":    row_count,
            "columns":      columns,
            "foreign_keys": FOREIGN_KEYS.get(table, []),
        })

    conn.close()
    return {"database": "tpch", "tables": tables}


def main() -> None:
    if not SQLITE_PATH.exists():
        print(f"ERROR: SQLite file not found: {SQLITE_PATH}")
        print("Run generate_tpch_sqlite.py first.")
        return

    print(f"\nReading: {SQLITE_PATH}")
    schema = extract_schema(SQLITE_PATH)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2))

    print(f"\nSchema summary:")
    for t in schema["tables"]:
        print(f"  {t['name']:<12} {t['row_count']:>10,} rows  {len(t['columns'])} columns  {len(t['foreign_keys'])} FKs")

    print(f"\nOutput: {OUTPUT_PATH}")
    print("Done.\n")


if __name__ == "__main__":
    main()
