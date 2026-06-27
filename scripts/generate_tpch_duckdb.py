"""
generate_tpch_duckdb.py
=======================
Generates TPC-H SF=1 data directly into a native DuckDB file using DuckDB's
built-in TPC-H extension. No SQLite involved.

Derived columns added:
  lineitem : l_net_revenue = l_extendedprice * (1 - l_discount)
             l_ship_year, l_ship_month
  orders   : o_year, o_month, o_quarter
  customer : c_has_debt, c_balance_tier

Usage:
    python scripts/generate_tpch_duckdb.py

Runtime: ~2-4 minutes at SF=1.
"""

import time
from pathlib import Path

import duckdb

SCALE_FACTOR = 1
DUCKDB_PATH  = Path("datasets/tpch/tpch.duckdb")

PLAIN_TABLES = ["region", "nation", "supplier", "part", "partsupp"]

TABLE_QUERIES = {
    "region":   "SELECT * FROM region",
    "nation":   "SELECT * FROM nation",
    "supplier": "SELECT * FROM supplier",
    "part":     "SELECT * FROM part",
    "partsupp": "SELECT * FROM partsupp",

    "customer": """
        SELECT
            *,
            CASE WHEN c_acctbal < 0 THEN 1 ELSE 0 END AS c_has_debt,
            CASE
                WHEN c_acctbal < 0     THEN 'negative'
                WHEN c_acctbal < 2500  THEN 'low'
                WHEN c_acctbal < 7500  THEN 'medium'
                ELSE                       'high'
            END AS c_balance_tier
        FROM customer
    """,

    "orders": """
        SELECT
            *,
            YEAR(o_orderdate)    AS o_year,
            MONTH(o_orderdate)   AS o_month,
            QUARTER(o_orderdate) AS o_quarter
        FROM orders
    """,

    "lineitem": """
        SELECT
            *,
            l_extendedprice * (1.0 - l_discount) AS l_net_revenue,
            YEAR(l_shipdate)  AS l_ship_year,
            MONTH(l_shipdate) AS l_ship_month
        FROM lineitem
    """,
}

EXPORT_ORDER = ["region", "nation", "supplier", "part", "partsupp",
                "customer", "orders", "lineitem"]


def generate(scale_factor: int, duckdb_path: Path) -> None:
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)

    if duckdb_path.exists():
        duckdb_path.unlink()
        print(f"Removed existing {duckdb_path}")

    total_start = time.time()
    print(f"\n{'='*55}")
    print(f"  TPC-H DuckDB Generator  (SF={scale_factor})")
    print(f"{'='*55}\n")

    # Step 1: Generate TPC-H data in memory
    print("Step 1 — Generating TPC-H data in memory...")
    conn = duckdb.connect()
    conn.execute("INSTALL tpch; LOAD tpch;")
    conn.execute(f"CALL dbgen(sf={scale_factor});")
    print("  TPC-H data generated.\n")

    # Step 2: Attach the output DuckDB file
    print(f"Step 2 — Attaching output file: {duckdb_path}")
    conn.execute(f"ATTACH '{duckdb_path}' AS out")
    print("  Attached.\n")

    # Step 3: Export each table with derived columns
    print("Step 3 — Exporting tables:\n")
    for table in EXPORT_ORDER:
        t_start = time.time()
        query = TABLE_QUERIES[table]
        conn.execute(f"CREATE TABLE out.{table} AS ({query})")
        elapsed = time.time() - t_start
        rows = conn.execute(f"SELECT COUNT(*) FROM out.{table}").fetchone()[0]
        print(f"  {table:<12} {rows:>10,} rows  ({elapsed:.1f}s)")

    conn.close()

    # Step 4: Verify
    print(f"\nStep 4 — Verifying {duckdb_path}...")
    verify = duckdb.connect(str(duckdb_path))
    tables = [r[0] for r in verify.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()]
    verify.close()

    missing = set(EXPORT_ORDER) - set(tables)
    print(f"  Tables found ({len(tables)}): {', '.join(sorted(tables))}")
    if missing:
        print(f"  ERROR — missing: {missing}")
    else:
        print("  All 8 tables verified.")

    total = time.time() - total_start
    size_mb = duckdb_path.stat().st_size / (1024 ** 2)
    print(f"\n{'='*55}")
    print(f"  Done in {total:.1f}s  |  File size: {size_mb:.1f} MB")
    print(f"  Output: {duckdb_path}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    generate(SCALE_FACTOR, DUCKDB_PATH)
