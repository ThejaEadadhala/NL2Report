import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import duckdb

conn = duckdb.connect("datasets/m5/m5.duckdb", read_only=True)
qs = json.load(open("datasets/m5/M5_Questions.json"))

ok, err = 0, 0
for q in qs:
    try:
        rows = conn.execute(q["gold_sql"]).fetchall()
        print(f"[{q['index']:3d}] OK   {len(rows)} rows  | {q['question'][:60]}")
        ok += 1
    except Exception as e:
        print(f"[{q['index']:3d}] ERR  {str(e)[:80]}  | {q['question'][:50]}")
        err += 1

conn.close()
print(f"\nTotal: {ok} OK, {err} errors out of {len(qs)}")
