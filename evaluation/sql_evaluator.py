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
    db_base: Path,
    model,
    schema_loader,
    max_questions: int | None = None,
) -> dict:
    """
    Run execution accuracy over a list of BIRD-format question dicts.

    questions    : list of dicts from dev.json / train.json
    db_base      : path to databases/dev or databases/train
    model        : any BaseModel instance
    schema_loader: callable(db_name) -> schema dict
    """
    total = 0
    correct = 0
    valid = 0
    errors = []

    subset = questions[:max_questions] if max_questions else questions

    for i, item in enumerate(subset):
        db_name = item["db_id"]
        question = item["question"]
        gold_sql = item["SQL"]

        db_path = db_base / db_name / f"{db_name}.sqlite"
        if not db_path.exists():
            continue

        try:
            schema = schema_loader(db_name)
            pred_sql = model.generate_sql(question, schema)
            result = execution_accuracy(gold_sql, pred_sql, db_path)
        except Exception as e:
            errors.append({"index": i, "db": db_name, "error": str(e)})
            total += 1
            continue

        total += 1
        if result["valid"]:
            valid += 1
        if result["match"]:
            correct += 1

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(subset)}] EX so far: {correct}/{total} ({100*correct/total:.1f}%)")

    return {
        "total": total,
        "correct": correct,
        "valid": valid,
        "execution_accuracy": round(correct / total, 4) if total else 0,
        "valid_sql_rate": round(valid / total, 4) if total else 0,
        "errors": errors,
    }
