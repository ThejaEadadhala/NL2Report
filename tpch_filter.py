"""
TPC-H Data Filtering Tool
==========================
Queries the cleaned TPC-H data from PostgreSQL.
Run tpch_pipeline.py first to populate the database.

Usage:
    python tpch_filter.py              # runs the demo examples
    from tpch_filter import connect, filter_orders   # import into your script
"""

import pandas as pd
import sqlalchemy
from sqlalchemy import text

# ── Connection ────────────────────────────────────────────────────────────────
PG_USER     = "postgres"
PG_PASSWORD = "theja"
PG_HOST     = "localhost"
PG_PORT     = 5432
PG_DATABASE = "tpch"

PG_URL = f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"


def connect() -> sqlalchemy.engine.Engine:
    """Return a SQLAlchemy engine connected to the TPC-H PostgreSQL database."""
    engine = sqlalchemy.create_engine(PG_URL)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print(f"✅ Connected to PostgreSQL — {PG_DATABASE}")
    return engine


def query(engine, sql: str) -> pd.DataFrame:
    """Run any SQL query and return a DataFrame."""
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)


# ── Filter functions ──────────────────────────────────────────────────────────

def filter_orders(
    engine,
    status: str | None = None,        # "F", "O", "P"
    priority: str | None = None,      # e.g. "1-URGENT"
    date_from: str | None = None,     # "YYYY-MM-DD"
    date_to: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
) -> pd.DataFrame:
    conditions = []
    if status:     conditions.append(f"o_orderstatus = '{status}'")
    if priority:   conditions.append(f"o_orderpriority = '{priority}'")
    if date_from:  conditions.append(f"o_orderdate >= '{date_from}'")
    if date_to:    conditions.append(f"o_orderdate <= '{date_to}'")
    if min_price:  conditions.append(f"o_totalprice >= {min_price}")
    if max_price:  conditions.append(f"o_totalprice <= {max_price}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return query(engine, f"SELECT * FROM orders {where} LIMIT 1000")


def filter_lineitem(
    engine,
    ship_mode: str | None = None,
    return_flag: str | None = None,   # "A", "N", "R"
    min_quantity: int | None = None,
    max_discount: float | None = None,
    ship_date_from: str | None = None,
    ship_date_to: str | None = None,
) -> pd.DataFrame:
    conditions = []
    if ship_mode:      conditions.append(f"l_shipmode = '{ship_mode}'")
    if return_flag:    conditions.append(f"l_returnflag = '{return_flag}'")
    if min_quantity:   conditions.append(f"l_quantity >= {min_quantity}")
    if max_discount is not None:
                       conditions.append(f"l_discount <= {max_discount}")
    if ship_date_from: conditions.append(f"l_shipdate >= '{ship_date_from}'")
    if ship_date_to:   conditions.append(f"l_shipdate <= '{ship_date_to}'")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return query(engine, f"SELECT * FROM lineitem {where} LIMIT 1000")


def filter_customers(
    engine,
    market_segment: str | None = None,
    nation_name: str | None = None,
    min_balance: float | None = None,
    max_balance: float | None = None,
) -> pd.DataFrame:
    conditions = []
    if market_segment: conditions.append(f"c_mktsegment = '{market_segment}'")
    if min_balance:    conditions.append(f"c_acctbal >= {min_balance}")
    if max_balance:    conditions.append(f"c_acctbal <= {max_balance}")
    if nation_name:    conditions.append(f"n_name = '{nation_name}'")
    join = "JOIN nation ON c_nationkey = n_nationkey" if nation_name else ""
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return query(engine, f"SELECT c.* FROM customer c {join} {where} LIMIT 1000")


def filter_parts(
    engine,
    brand: str | None = None,
    part_type: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    container: str | None = None,
) -> pd.DataFrame:
    conditions = []
    if brand:     conditions.append(f"p_brand = '{brand}'")
    if part_type: conditions.append(f"p_type ILIKE '%{part_type}%'")
    if min_size:  conditions.append(f"p_size >= {min_size}")
    if max_size:  conditions.append(f"p_size <= {max_size}")
    if container: conditions.append(f"p_container = '{container}'")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return query(engine, f"SELECT * FROM part {where} LIMIT 1000")


# ── Demo ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = connect()

    print("\n📦 EXAMPLE 1 — Urgent orders in 1995 over $50,000:")
    df1 = filter_orders(engine, priority="1-URGENT",
                        date_from="1995-01-01", date_to="1995-12-31",
                        min_price=50000)
    print(f"   {len(df1)} rows")
    print(df1[["o_orderkey", "o_orderdate", "o_totalprice", "o_orderpriority"]].head())

    print("\n✈️  EXAMPLE 2 — Air-shipped lineitems, discount ≤ 5%:")
    df2 = filter_lineitem(engine, ship_mode="AIR", max_discount=0.05)
    print(f"   {len(df2)} rows")
    print(df2[["l_orderkey", "l_quantity", "l_extendedprice", "l_discount"]].head())

    print("\n👤 EXAMPLE 3 — AUTOMOBILE customers in CANADA, positive balance:")
    df3 = filter_customers(engine, market_segment="AUTOMOBILE",
                           nation_name="CANADA", min_balance=0)
    print(f"   {len(df3)} rows")
    print(df3[["c_custkey", "c_name", "c_acctbal"]].head())

    print("\n🔍 EXAMPLE 4 — Revenue by ship mode:")
    df4 = query(engine, """
        SELECT l_shipmode,
               COUNT(*)                                            AS line_count,
               ROUND(SUM(l_extendedprice * (1 - l_discount))::numeric, 2) AS revenue
        FROM lineitem
        GROUP BY l_shipmode
        ORDER BY revenue DESC
    """)
    print(df4)

    print("\n✅ Done.")
