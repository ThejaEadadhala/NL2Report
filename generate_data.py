import duckdb
import os

os.makedirs("raw", exist_ok=True)

print("Connecting to DuckDB...")
con = duckdb.connect()

print("Installing TPC-H extension...")
con.execute("INSTALL tpch;")
con.execute("LOAD tpch;")

print("Generating SF=1 data (~1GB, takes 2-3 minutes)...")
con.execute("CALL dbgen(sf=1);")

tables = ["customer", "lineitem", "nation", "orders",
          "part", "partsupp", "region", "supplier"]

print("Exporting tables to raw/ folder...")
for t in tables:
    con.execute(f"COPY {t} TO 'raw/{t}.csv' (HEADER, DELIMITER ',');")
    count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  exported {t}.csv  ({count:,} rows)")

print("\nDone! All 8 tables saved to raw/")