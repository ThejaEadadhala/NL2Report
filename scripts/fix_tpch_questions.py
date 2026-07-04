"""Fix TPC_H_Questions.json: clean fields and convert SQLite date functions to DuckDB."""
import json
import re
from pathlib import Path

INPUT = Path("datasets/tpch/TPC_H_Questions.json")
data = json.loads(INPUT.read_text(encoding="utf-8"))


def fix_sql(sql: str) -> str:
    # STRFTIME('%Y', col) -> strftime(col, '%Y')
    sql = re.sub(
        r"STRFTIME\('%Y',\s*([^)]+)\)",
        lambda m: f"strftime({m.group(1).strip()}, '%Y')",
        sql,
    )
    # STRFTIME('%Y-%m', col) -> strftime(col, '%Y-%m')
    sql = re.sub(
        r"STRFTIME\('%Y-%m',\s*([^)]+)\)",
        lambda m: f"strftime({m.group(1).strip()}, '%Y-%m')",
        sql,
    )
    # JULIANDAY(a) - JULIANDAY(b) -> datediff('day', b, a)
    sql = re.sub(
        r"JULIANDAY\(([^)]+)\)\s*-\s*JULIANDAY\(([^)]+)\)",
        lambda m: f"datediff('day', {m.group(2).strip()}, {m.group(1).strip()})",
        sql,
    )
    return sql


cleaned = []
for i, q in enumerate(data):
    cleaned.append({
        "index": i,
        "db": "tpch",
        "question": q["question"],
        "gold_sql": fix_sql(q["SQL"]),
    })

INPUT.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Written {len(cleaned)} questions.")

# Verify no SQLite-specific functions remain
issues = [(q["index"], q["question"]) for q in cleaned
          if "STRFTIME" in q["gold_sql"] or "JULIANDAY" in q["gold_sql"]]
if issues:
    print("REMAINING ISSUES:")
    for idx, q in issues:
        print(f"  [{idx}] {q}")
else:
    print("All SQLite date functions fixed.")

print("Sample keys:", list(cleaned[0].keys()))
