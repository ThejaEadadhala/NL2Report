import json

data = json.load(open("results/m5_anthropic_results.json"))

print(f"Total results so far: {len(data)}\n")

for r in data[22:29]:
    print(f"[{r['index']}] {r['question'][:65]}")
    print(f"  match          : {r.get('match')}  valid: {r.get('valid')}")
    print(f"  gold_row_count : {r.get('gold_row_count')}")
    print(f"  pred_row_count : {r.get('pred_row_count')}")
    print(f"  pred_error     : {str(r.get('pred_error', ''))[:150]}")
    print(f"  gold_sql       : {r.get('gold_sql', '')[:150]}")
    print()
