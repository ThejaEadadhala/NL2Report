"""Add 19 new valid M5 questions to reach 100 total. Uses only calendar, sales, sales_evaluation."""
import json, duckdb
from pathlib import Path

PATH  = Path("datasets/m5/M5_Questions.json")
DUCKDB = "datasets/m5/m5.duckdb"

new_questions = [
    {
        "question": "What are total evaluation period sales by product category?",
        "gold_sql": "SELECT cat_id, SUM(sales) AS total_sales FROM sales_evaluation GROUP BY cat_id ORDER BY total_sales DESC",
    },
    {
        "question": "Which store had the highest total sales in the evaluation period?",
        "gold_sql": "SELECT store_id, SUM(sales) AS total_sales FROM sales_evaluation GROUP BY store_id ORDER BY total_sales DESC LIMIT 1",
    },
    {
        "question": "What are total sales by state in the evaluation period?",
        "gold_sql": "SELECT state_id, SUM(sales) AS total_sales FROM sales_evaluation GROUP BY state_id ORDER BY total_sales DESC",
    },
    {
        "question": "Which department had the highest sales in the evaluation period?",
        "gold_sql": "SELECT dept_id, SUM(sales) AS total_sales FROM sales_evaluation GROUP BY dept_id ORDER BY total_sales DESC LIMIT 1",
    },
    {
        "question": "What are total evaluation period sales by department?",
        "gold_sql": "SELECT dept_id, SUM(sales) AS total_sales FROM sales_evaluation GROUP BY dept_id ORDER BY total_sales DESC",
    },
    {
        "question": "What are the combined total sales from validation and evaluation periods by product category?",
        "gold_sql": "SELECT cat_id, SUM(sales) AS total_sales FROM (SELECT cat_id, sales FROM sales UNION ALL SELECT cat_id, sales FROM sales_evaluation) AS combined GROUP BY cat_id ORDER BY total_sales DESC",
    },
    {
        "question": "How many days had total sales above 50000?",
        "gold_sql": "SELECT COUNT(*) AS days_above_50000 FROM (SELECT d, SUM(sales) AS daily_sales FROM sales GROUP BY d HAVING SUM(sales) > 50000) AS t",
    },
    {
        "question": "What are total sales on days with sporting events?",
        "gold_sql": "SELECT SUM(s.sales) AS total_sales FROM sales AS s JOIN calendar AS c ON s.d = c.d WHERE c.event_type_1 = 'Sporting' OR c.event_type_2 = 'Sporting'",
    },
    {
        "question": "What are total sales on days with religious events?",
        "gold_sql": "SELECT SUM(s.sales) AS total_sales FROM sales AS s JOIN calendar AS c ON s.d = c.d WHERE c.event_type_1 = 'Religious' OR c.event_type_2 = 'Religious'",
    },
    {
        "question": "What are total sales on days with cultural events?",
        "gold_sql": "SELECT SUM(s.sales) AS total_sales FROM sales AS s JOIN calendar AS c ON s.d = c.d WHERE c.event_type_1 = 'Cultural' OR c.event_type_2 = 'Cultural'",
    },
    {
        "question": "Which 10 items had the highest total sales in the evaluation period?",
        "gold_sql": "SELECT item_id, SUM(sales) AS total_sales FROM sales_evaluation GROUP BY item_id ORDER BY total_sales DESC LIMIT 10",
    },
    {
        "question": "What are total sales by department for the FOODS category?",
        "gold_sql": "SELECT dept_id, SUM(sales) AS total_sales FROM sales WHERE cat_id = 'FOODS' GROUP BY dept_id ORDER BY total_sales DESC",
    },
    {
        "question": "What are total sales by month for HOUSEHOLD products?",
        "gold_sql": "SELECT c.month, SUM(s.sales) AS total_sales FROM sales AS s JOIN calendar AS c ON s.d = c.d WHERE s.cat_id = 'HOUSEHOLD' GROUP BY c.month ORDER BY c.month",
    },
    {
        "question": "Which state had the highest total sales for HOBBIES products?",
        "gold_sql": "SELECT state_id, SUM(sales) AS total_sales FROM sales WHERE cat_id = 'HOBBIES' GROUP BY state_id ORDER BY total_sales DESC LIMIT 1",
    },
    {
        "question": "What are total sales by state for HOUSEHOLD products?",
        "gold_sql": "SELECT state_id, SUM(sales) AS total_sales FROM sales WHERE cat_id = 'HOUSEHOLD' GROUP BY state_id ORDER BY total_sales DESC",
    },
    {
        "question": "What is the total number of units sold across all stores and days in the validation period?",
        "gold_sql": "SELECT SUM(sales) AS total_units_sold FROM sales",
    },
    {
        "question": "How many distinct items are tracked in the sales table?",
        "gold_sql": "SELECT COUNT(DISTINCT item_id) AS distinct_items FROM sales",
    },
    {
        "question": "What are total sales by store for HOBBIES products?",
        "gold_sql": "SELECT store_id, SUM(sales) AS total_sales FROM sales WHERE cat_id = 'HOBBIES' GROUP BY store_id ORDER BY total_sales DESC",
    },
    {
        "question": "What are total sales by department for store CA_1?",
        "gold_sql": "SELECT dept_id, SUM(sales) AS total_sales FROM sales WHERE store_id = 'CA_1' GROUP BY dept_id ORDER BY total_sales DESC",
    },
]

data = json.loads(PATH.read_text(encoding="utf-8"))
start_idx = len(data)

for i, q in enumerate(new_questions):
    data.append({"index": start_idx + i, "db": "m5", **q})

# Validate new questions
con = duckdb.connect(DUCKDB, read_only=True)
errors = []
for q in data[start_idx:]:
    try:
        con.execute(q["gold_sql"]).fetchone()
    except Exception as e:
        errors.append((q["index"], q["question"][:60], str(e)[:100]))
con.close()

if errors:
    print("FAILED:")
    for idx, q, e in errors:
        print(f"  [{idx}] {q} -- {e}")
else:
    PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Total questions: {len(data)}")
    print(f"Added {len(new_questions)} new questions. All validate successfully.")
