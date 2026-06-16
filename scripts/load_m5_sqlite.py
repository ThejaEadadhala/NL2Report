"""
load_m5_sqlite.py
=================
Loads the M5 Forecasting dataset CSVs into datasets/m5/m5.sqlite.

Transformations:
  sales_train_validation.csv  ->  sales table (unpivoted wide->long: d_1..d_1913 become rows)
  calendar.csv                ->  calendar table (loaded as-is)
  sell_prices.csv             ->  sell_prices table (loaded as-is, if present)

Notes:
  - sales_train_evaluation.csv is loaded as sales_evaluation if present (extends validation by 28 days)
  - sell_prices.csv is optional — script continues without it if missing
  - Unpivot uses DuckDB for efficiency (~58M rows from validation alone)

Usage (from project root):
    python scripts/load_m5_sqlite.py

Runtime: ~5-15 minutes depending on hardware.
"""

import time
from pathlib import Path

import duckdb

# ── Paths ──────────────────────────────────────────────────────────────────────

M5_DIR     = Path("datasets/m5")
SQLITE_PATH = M5_DIR / "m5.sqlite"

# Meta columns that stay as identifier columns (not unpivoted)
SALES_ID_COLS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]


def load_table_direct(conn, csv_path: Path, table_name: str) -> int:
    """Load a CSV directly into SQLite without transformation."""
    conn.execute(f"""
        CREATE TABLE m5.{table_name} AS
        SELECT * FROM read_csv('{csv_path}', header=true, auto_detect=true)
    """)
    return conn.execute(f"SELECT COUNT(*) FROM m5.{table_name}").fetchone()[0]


def load_sales_unpivoted(conn, csv_path: Path, table_name: str, max_day: int) -> int:
    """
    Load a wide-format sales CSV and unpivot day columns (d_1..d_N) to long format.
    Uses DuckDB UNPIVOT with COLUMNS regex for efficiency.
    """
    exclude = ", ".join(SALES_ID_COLS)
    conn.execute(f"""
        CREATE TABLE m5.{table_name} AS
        SELECT
            id, item_id, dept_id, cat_id, store_id, state_id,
            d,
            CAST(sales AS INTEGER) AS sales
        FROM (
            UNPIVOT (
                SELECT * FROM read_csv('{csv_path}', header=true, auto_detect=true)
            )
            ON COLUMNS(* EXCLUDE ({exclude}))
            INTO NAME d VALUE sales
        )
    """)
    return conn.execute(f"SELECT COUNT(*) FROM m5.{table_name}").fetchone()[0]


def main() -> None:
    # Remove existing SQLite file so we start clean
    if SQLITE_PATH.exists():
        SQLITE_PATH.unlink()
        print(f"Removed existing {SQLITE_PATH}")

    total_start = time.time()
    print(f"\n{'='*55}")
    print(f"  M5 SQLite Loader")
    print(f"{'='*55}\n")

    conn = duckdb.connect()
    conn.execute("INSTALL sqlite; LOAD sqlite;")
    conn.execute(f"ATTACH '{SQLITE_PATH}' AS m5 (TYPE SQLITE);")

    # ── 1. calendar ────────────────────────────────────────────────────────────
    csv = M5_DIR / "calendar.csv"
    print("Loading calendar.csv...")
    t = time.time()
    rows = load_table_direct(conn, csv, "calendar")
    print(f"  calendar        {rows:>12,} rows  ({time.time()-t:.1f}s)\n")

    # ── 2. sell_prices (optional) ──────────────────────────────────────────────
    csv = M5_DIR / "sell_prices.csv"
    if csv.exists():
        print("Loading sell_prices.csv...")
        t = time.time()
        rows = load_table_direct(conn, csv, "sell_prices")
        print(f"  sell_prices     {rows:>12,} rows  ({time.time()-t:.1f}s)\n")
    else:
        print("  sell_prices.csv not found — skipping (table will not exist in SQLite)\n")

    # ── 3. sales_train_validation (wide -> long) ───────────────────────────────
    csv = M5_DIR / "sales_train_validation.csv"
    print("Loading + unpivoting sales_train_validation.csv  (d_1 .. d_1913 -> rows)...")
    print("  This may take several minutes for ~58M rows...")
    t = time.time()
    rows = load_sales_unpivoted(conn, csv, "sales", max_day=1913)
    print(f"  sales           {rows:>12,} rows  ({time.time()-t:.1f}s)\n")

    # ── 4. sales_train_evaluation (optional, extends validation by 28 days) ────
    csv = M5_DIR / "sales_train_evaluation.csv"
    if csv.exists():
        print("Loading + unpivoting sales_train_evaluation.csv  (d_1 .. d_1941 -> rows)...")
        print("  This may take several minutes for ~59M rows...")
        t = time.time()
        rows = load_sales_unpivoted(conn, csv, "sales_evaluation", max_day=1941)
        print(f"  sales_evaluation {rows:>11,} rows  ({time.time()-t:.1f}s)\n")

    conn.close()

    # ── Verify ─────────────────────────────────────────────────────────────────
    print("Verifying SQLite file...\n")
    import sqlite3
    verify = sqlite3.connect(SQLITE_PATH)
    cursor = verify.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall()]
    for t in tables:
        cursor.execute(f"SELECT COUNT(*) FROM '{t}';")
        n = cursor.fetchone()[0]
        print(f"  {t:<25} {n:>12,} rows")
    verify.close()

    elapsed = time.time() - total_start
    size_mb = SQLITE_PATH.stat().st_size / (1024 ** 2)
    print(f"\n{'='*55}")
    print(f"  Done in {elapsed:.1f}s  |  File size: {size_mb:.1f} MB")
    print(f"  Output: {SQLITE_PATH}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
