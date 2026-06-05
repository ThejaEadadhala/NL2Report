"""
generate_tpch_sqlite.py
=======================
Generates TPC-H SF=1 data using DuckDB's built-in TPC-H extension and exports
all 8 tables (plus derived columns) directly to datasets/tpch/tpch.sqlite.

Derived columns added:
  lineitem : l_net_revenue, l_ship_year, l_ship_month
  orders   : o_year, o_month, o_quarter
  customer : c_has_debt

Usage:
    python generate_tpch_sqlite.py

Runtime: ~3-5 minutes at SF=1 (~6 million lineitem rows).
"""

import sqlite3
import time
from pathlib import Path

import duckdb

# ── Configuration ──────────────────────────────────────────────────────────────

SCALE_FACTOR = 1                                        # SF=1 ≈ 1 GB raw data
SQLITE_PATH  = Path("datasets/tpch/tpch.sqlite")

# Tables exported as-is (no derived columns needed)
PLAIN_TABLES = ["region", "nation", "supplier", "part", "partsupp"]

# ── Table export queries ────────────────────────────────────────────────────────
# Each SELECT defines the final shape of the table written to SQLite.

TABLE_QUERIES = {
    "region":    "SELECT * FROM region",
    "nation":    "SELECT * FROM nation",
    "supplier":  "SELECT * FROM supplier",
    "part":      "SELECT * FROM part",
    "partsupp":  "SELECT * FROM partsupp",

    "customer": """
        SELECT
            *,
            CASE WHEN c_acctbal < 0 THEN 1 ELSE 0 END AS c_has_debt
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
            l_extendedprice * (1.0 - l_discount) * (1.0 + l_tax) AS l_net_revenue,
            YEAR(l_shipdate)  AS l_ship_year,
            MONTH(l_shipdate) AS l_ship_month
        FROM lineitem
    """,
}

# Canonical TPC-H export order (parent tables before child tables)
EXPORT_ORDER = ["region", "nation", "supplier", "part", "partsupp",
                "customer", "orders", "lineitem"]


def generate(scale_factor: int, sqlite_path: Path) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove any existing SQLite file so we start clean
    if sqlite_path.exists():
        sqlite_path.unlink()
        print(f"Removed existing {sqlite_path}")

    total_start = time.time()
    print(f"\n{'='*55}")
    print(f"  TPC-H SQLite Generator  (SF={scale_factor})")
    print(f"{'='*55}\n")

    # ── Step 1: Generate TPC-H data in DuckDB ──────────────────────────────────
    print("Step 1 — Generating TPC-H data in DuckDB...")
    conn = duckdb.connect()
    conn.execute("LOAD tpch;")
    conn.execute(f"CALL dbgen(sf={scale_factor});")
    print("  TPC-H data generated.\n")

    # ── Step 2: Load SQLite extension and attach output file ───────────────────
    print(f"Step 2 — Attaching SQLite file: {sqlite_path}")
    conn.execute("INSTALL sqlite; LOAD sqlite;")
    conn.execute(f"ATTACH '{sqlite_path}' AS tpch_db (TYPE SQLITE);")
    print("  SQLite file attached.\n")

    # ── Step 3: Export each table ──────────────────────────────────────────────
    print("Step 3 — Exporting tables to SQLite:\n")
    for table in EXPORT_ORDER:
        t_start = time.time()
        query = TABLE_QUERIES[table]
        conn.execute(f"CREATE TABLE tpch_db.{table} AS ({query});")
        elapsed = time.time() - t_start

        # Row count straight from SQLite to confirm
        rows = conn.execute(f"SELECT COUNT(*) FROM tpch_db.{table}").fetchone()[0]
        print(f"  {table:<12} {rows:>10,} rows  ({elapsed:.1f}s)")

    conn.close()

    # ── Step 4: Verify all 8 tables in the SQLite file ─────────────────────────
    print(f"\nStep 4 — Verifying SQLite file: {sqlite_path}\n")
    conn_verify = sqlite3.connect(sqlite_path)
    cursor = conn_verify.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    found = [row[0] for row in cursor.fetchall()]
    conn_verify.close()

    expected = set(EXPORT_ORDER)
    missing  = expected - set(found)

    print(f"  Tables found ({len(found)}): {', '.join(sorted(found))}")
    if missing:
        print(f"\n  ERROR — missing tables: {missing}")
    else:
        print(f"  All 8 tables verified. ✓")

    total = time.time() - total_start
    size_mb = sqlite_path.stat().st_size / (1024 ** 2)
    print(f"\n{'='*55}")
    print(f"  Done in {total:.1f}s  |  File size: {size_mb:.1f} MB")
    print(f"  Output: {sqlite_path}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    generate(SCALE_FACTOR, SQLITE_PATH)
