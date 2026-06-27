"""
generate_m5_duckdb.py
=====================
Loads M5 Forecasting dataset CSV files into a native DuckDB file.

  calendar.csv        -> calendar table  (DuckDB native CSV reader)
  sell_prices.csv     -> sell_prices table (DuckDB native CSV reader, optional)
  sales_train_validation.csv -> sales table (pandas melt wide->long, 5M-row chunks)

CSV files are read from datasets/m5/raw/ if that directory exists,
otherwise falls back to datasets/m5/.

Usage:
    python scripts/generate_m5_duckdb.py

Runtime: ~5-15 minutes depending on hardware.
"""

import time
from pathlib import Path

import duckdb
import pandas as pd

M5_DIR      = Path("datasets/m5")
DUCKDB_PATH = M5_DIR / "m5.duckdb"
RAW_DIR     = M5_DIR / "raw"

ID_COLS    = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
CHUNK_ROWS = 3000   # ~5.7M rows after melt per chunk


def find_csv(filename: str) -> Path:
    """Return path to CSV: prefer raw/ subdirectory, fall back to m5/ root."""
    candidate = RAW_DIR / filename
    if candidate.exists():
        return candidate
    return M5_DIR / filename


def main() -> None:
    if DUCKDB_PATH.exists():
        DUCKDB_PATH.unlink()
        print(f"Removed existing {DUCKDB_PATH}")

    total_start = time.time()
    print(f"\n{'='*55}")
    print(f"  M5 DuckDB Loader")
    print(f"{'='*55}\n")

    conn = duckdb.connect(str(DUCKDB_PATH))

    # ── 1. calendar ────────────────────────────────────────────────────────────
    csv = find_csv("calendar.csv")
    if not csv.exists():
        raise FileNotFoundError(f"calendar.csv not found (tried {csv})")

    print(f"Loading calendar from {csv}...")
    t = time.time()
    conn.execute(f"""
        CREATE TABLE calendar AS
        SELECT * FROM read_csv('{csv}', header=true, auto_detect=true)
    """)
    n = conn.execute("SELECT COUNT(*) FROM calendar").fetchone()[0]
    print(f"  calendar        {n:>12,} rows  ({time.time()-t:.1f}s)\n")

    # ── 2. sell_prices (optional) ──────────────────────────────────────────────
    csv = find_csv("sell_prices.csv")
    if csv.exists():
        print(f"Loading sell_prices from {csv}...")
        t = time.time()
        conn.execute(f"""
            CREATE TABLE sell_prices AS
            SELECT * FROM read_csv('{csv}', header=true, auto_detect=true)
        """)
        n = conn.execute("SELECT COUNT(*) FROM sell_prices").fetchone()[0]
        print(f"  sell_prices     {n:>12,} rows  ({time.time()-t:.1f}s)\n")
    else:
        print("  sell_prices.csv not found — skipping.\n")

    # ── 3. sales + sales_evaluation (pandas melt wide→long, chunked) ───────────
    for table_name, csv_name in [
        ("sales", "sales_train_validation.csv"),
        ("sales_evaluation", "sales_train_evaluation.csv"),
    ]:
        csv = find_csv(csv_name)
        if not csv.exists():
            print(f"  {csv_name} not found — skipping {table_name}.\n")
            continue

        print(f"Loading + unpivoting {table_name} from {csv}")
        print(f"  Using pandas melt with {CHUNK_ROWS}-row input chunks (~5M rows/chunk)...")

        conn.execute(f"""
            CREATE TABLE {table_name} (
                id       VARCHAR,
                item_id  VARCHAR,
                dept_id  VARCHAR,
                cat_id   VARCHAR,
                store_id VARCHAR,
                state_id VARCHAR,
                d        VARCHAR,
                sales    INTEGER
            )
        """)

        t = time.time()
        total_rows = 0
        chunk_num  = 0

        for chunk_df in pd.read_csv(csv, chunksize=CHUNK_ROWS):
            melted = chunk_df.melt(
                id_vars=ID_COLS,
                var_name="d",
                value_name="sales",
            )
            melted["sales"] = melted["sales"].fillna(0).astype(int)
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM melted")
            total_rows += len(melted)
            chunk_num  += 1
            print(f"  chunk {chunk_num}  {total_rows:>12,} rows total...", end="\r")

        print(f"\n  {table_name:<20} {total_rows:>12,} rows  ({time.time()-t:.1f}s)\n")

    conn.close()

    # ── Verify ─────────────────────────────────────────────────────────────────
    print("Verifying DuckDB file...\n")
    verify = duckdb.connect(str(DUCKDB_PATH))
    tables = [r[0] for r in verify.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()]
    for tbl in tables:
        n = verify.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl:<25} {n:>12,} rows")
    verify.close()

    elapsed  = time.time() - total_start
    size_mb  = DUCKDB_PATH.stat().st_size / (1024 ** 2)
    print(f"\n{'='*55}")
    print(f"  Done in {elapsed:.1f}s  |  File size: {size_mb:.1f} MB")
    print(f"  Output: {DUCKDB_PATH}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
