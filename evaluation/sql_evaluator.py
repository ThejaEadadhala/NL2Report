"""
sql_evaluator.py
Measures SQL generation quality:
  - Execution Accuracy (EX): predicted SQL returns same result as gold SQL
  - Valid SQL Rate: percentage of queries that execute without error
"""

import sqlite3
from pathlib import Path


def _execute(db_path: Path, sql: str) -> tuple[list, str | None]:
    """Execute SQL and return (rows, error). Rows are sorted sets for order-independent comparison."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()
        return sorted([tuple(str(v) for v in row) for row in rows]), None
    except Exception as e:
        return [], str(e)


def execution_accuracy(gold_sql: str, pred_sql: str, db_path: Path) -> dict:
    """Compare predicted SQL result against gold SQL result."""
    gold_rows, gold_err = _execute(db_path, gold_sql)
    pred_rows, pred_err = _execute(db_path, pred_sql)

    return {
        "match": gold_rows == pred_rows and pred_err is None,
        "valid": pred_err is None,
        "gold_error": gold_err,
        "pred_error": pred_err,
        "gold_row_count": len(gold_rows),
        "pred_row_count": len(pred_rows),
    }


def evaluate_dataset(
    questions: list[dict],
    db_finder,
    model,
    schema_loader,
    max_questions: int | None = None,
) -> dict:
    """
    Run execution accuracy over a list of BIRD-format question dicts.

    questions  : list of dicts with keys: db_id, question, SQL
    db_finder  : callable(db_name) -> Path to .sqlite file
    model      : any BaseModel instance
    schema_loader: callable(db_name) -> schema dict
    """
    total = 0
    correct = 0
    valid = 0
    rows_per_question = []

    subset = questions[:max_questions] if max_questions else questions

    for i, item in enumerate(subset):
        db_name = item["db_id"]
        question = item["question"]
        gold_sql = item["SQL"]

        db_path = db_finder(db_name)
        if db_path is None or not db_path.exists():
            continue

        record = {
            "index": i,
            "db": db_name,
            "question": question,
            "gold_sql": gold_sql,
            "pred_sql": None,
            "match": False,
            "valid": False,
            "pred_error": None,
            "gold_row_count": None,
            "pred_row_count": None,
        }

        try:
            schema = schema_loader(db_name)
            pred_sql = model.generate_sql(question, schema)
            result = execution_accuracy(gold_sql, pred_sql, db_path)

            record.update({
                "pred_sql": pred_sql,
                "match": result["match"],
                "valid": result["valid"],
                "pred_error": result["pred_error"],
                "gold_row_count": result["gold_row_count"],
                "pred_row_count": result["pred_row_count"],
            })
        except Exception as e:
            record["pred_error"] = str(e)

        rows_per_question.append(record)
        total += 1
        if record["valid"]:
            valid += 1
        if record["match"]:
            correct += 1

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(subset)}] EX so far: {correct}/{total} ({100*correct/total:.1f}%)")

    return {
        "summary": {
            "total": total,
            "correct": correct,
            "valid": valid,
            "execution_accuracy": round(correct / total, 4) if total else 0,
            "valid_sql_rate": round(valid / total, 4) if total else 0,
        },
        "results": rows_per_question,
    }
