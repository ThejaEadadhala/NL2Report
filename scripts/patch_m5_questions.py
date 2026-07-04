"""Patch the 5 remaining failing M5 questions."""
import json, duckdb
from pathlib import Path

QUARTER = "CASE WHEN c.month BETWEEN 1 AND 3 THEN 1 WHEN c.month BETWEEN 4 AND 6 THEN 2 WHEN c.month BETWEEN 7 AND 9 THEN 3 ELSE 4 END AS quarter"

patches = {
    13: "SELECT " + QUARTER + ", SUM(s.sales) AS total_sales FROM sales AS s JOIN calendar AS c ON s.d = c.d GROUP BY quarter ORDER BY quarter",
    31: "SELECT " + QUARTER + ", SUM(s.sales) AS total_sales FROM sales AS s JOIN calendar AS c ON s.d = c.d WHERE c.year = 2016 GROUP BY quarter ORDER BY quarter",
    37: "SELECT wm_yr_wk % 100 AS week_of_year, SUM(s.sales) AS total_sales FROM sales AS s JOIN calendar AS c ON s.d = c.d GROUP BY week_of_year ORDER BY week_of_year",
    43: "SELECT s.cat_id, " + QUARTER + ", SUM(s.sales) AS total_sales FROM sales AS s JOIN calendar AS c ON s.d = c.d GROUP BY s.cat_id, quarter ORDER BY s.cat_id, quarter",
    79: "SELECT s.state_id, CASE WHEN c.weekday IN ('Saturday', 'Sunday') THEN 1 ELSE 0 END AS is_weekend, SUM(s.sales) AS total_sales FROM sales AS s JOIN calendar AS c ON s.d = c.d GROUP BY s.state_id, is_weekend ORDER BY s.state_id, is_weekend",
}

path = Path("datasets/m5/M5_Questions.json")
data = json.loads(path.read_text(encoding="utf-8"))

for q in data:
    if q["index"] in patches:
        q["gold_sql"] = patches[q["index"]]

path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# Validate all
con = duckdb.connect("datasets/m5/m5.duckdb", read_only=True)
errors = []
for q in data:
    try:
        con.execute(q["gold_sql"]).fetchone()
    except Exception as e:
        errors.append((q["index"], q["question"][:60], str(e)[:100]))
con.close()

if errors:
    print("STILL FAILING:")
    for idx, q, e in errors:
        print(f"  [{idx}] {q} -- {e}")
else:
    print(f"All {len(data)} gold SQL queries execute successfully on DuckDB.")
