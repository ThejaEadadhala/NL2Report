"""
batch_eval.py
Batch evaluation pipeline: planning → SQL generation → execution → comparison.

Resumes from existing output file if interrupted. Saves after every question.

Usage:
    python pipeline/batch_eval.py --dataset tpch --model ollama --questions datasets/tpch/tpch_questions.json
    python pipeline/batch_eval.py --dataset bird --model anthropic --questions datasets/bird/sample_questions.json
    python pipeline/batch_eval.py --dataset tpch --model anthropic --questions datasets/tpch/tpch_questions.json --output results/tpch_anthropic.json
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DEFAULT_MODEL
from pipeline.planning_agent import PlanningAgent
from pipeline.run_analysis import get_model, load_schema, schema_engine, find_database_ref, execute_sql
from pipeline.single_grain_compiler import compile_single_grain_sql
from pipeline.vector_filter import apply_vector_filter
from scripts.judge_pred_sql import judge_results_file

QUERY_TIMEOUT = 300


def load_questions(path: Path) -> list[dict]:
    """Load questions JSON. Accepts both db_id/SQL and db/gold_sql field names."""
    items = json.loads(path.read_text(encoding="utf-8"))
    normalized = []
    for i, item in enumerate(items):
        normalized.append({
            "index": item.get("index", i),
            "db": item.get("db") or item.get("db_id"),
            "question": item["question"],
            "gold_sql": item.get("gold_sql") or item.get("SQL"),
        })
    return normalized


def load_existing_results(output_path: Path) -> dict[int, dict]:
    if not output_path.exists():
        return {}
    try:
        results = json.loads(output_path.read_text(encoding="utf-8"))
        return {r["index"]: r for r in results}
    except Exception:
        return {}


def save_results(results: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")


def result_file_complete(existing: dict[int, dict], questions: list[dict]) -> bool:
    return bool(questions) and all(question["index"] in existing for question in questions)


def run_judge(
    result_path: Path,
    judge_model: str,
    judge_openai_mode: str,
    judge_batch_size: int,
    judge_output: Path | None = None,
) -> None:
    print(f"\nJudging completed result file: {result_path}")
    report = judge_results_file(
        input_path=result_path,
        output_path=judge_output,
        judge_model=judge_model,
        openai_mode=judge_openai_mode,
        batch_size=judge_batch_size,
    )
    summary = report["summary"]
    print("\nLLM Judge Summary")
    print(f"  Total               : {summary['total']}")
    print(f"  Scored              : {summary['scored']}")
    print(f"  Correctness percent : {summary['correctness_percent']:.2f}%")
    print(f"  Verdict counts      : {summary['verdict_counts']}")
    print(f"  Output              : {report['output']}")


def _execute_raw(db_ref, sql: str, engine: str) -> list[tuple]:
    """Execute SQL without read-only validation (used for trusted gold SQL)."""
    if engine == "mysql":
        import mysql.connector
        conn = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=str(db_ref),
        )
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            return list(cursor.fetchall())
        finally:
            cursor.close()
            conn.close()
    elif engine == "duckdb":
        import duckdb
        conn = duckdb.connect(str(db_ref), read_only=True)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(str(db_ref))
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            conn.close()


def rows_match(gold_rows: list, pred_rows: list) -> bool:
    normalize = lambda rows: sorted([tuple(str(v) for v in row) for row in rows])
    return normalize(gold_rows) == normalize(pred_rows)


def process_question(item: dict, dataset: str, model, schema: dict, db_ref, engine: str) -> dict:
    """Run full pipeline for one question. Returns result dict."""
    question = item["question"]
    gold_sql = item["gold_sql"]

    subtasks = [question] if dataset == "beaver" else PlanningAgent(model).plan(question, schema)
    pred_sql = model.generate_sql(subtasks[0], schema)
    pred_sql, compile_report = compile_single_grain_sql(pred_sql)
    compiler_actions = list(compile_report.actions)
    if compiler_actions:
        print("  [Compiler] Applied actions:")
        for action in compiler_actions:
            print(f"    - {action}")

    try:
        gold_rows = _execute_raw(db_ref, gold_sql, engine)
        gold_row_count = len(gold_rows)
        gold_error = None
    except Exception as e:
        gold_rows = []
        gold_row_count = 0
        gold_error = str(e)

    try:
        _, pred_rows_raw = execute_sql(db_ref, pred_sql, engine)
        pred_rows = [tuple(r) for r in pred_rows_raw]
        pred_row_count = len(pred_rows)
        pred_error = None
        valid = True
        repair_status = "not_needed"
        repaired_sql = None
    except Exception as e:
        first_error = str(e)
        pred_rows = []
        pred_row_count = 0
        pred_error = first_error
        valid = False
        repaired_sql = None

        if hasattr(model, "repair_sql"):
            repair_status = "attempted"
            print("  [Repair] Execution failed. Attempting LLM SQL repair...")
            try:
                repaired_sql = model.repair_sql(pred_sql, [first_error], schema)
                repaired_sql, repair_compile_report = compile_single_grain_sql(repaired_sql)
                if repair_compile_report.actions:
                    compiler_actions.extend(repair_compile_report.actions)
                    print("  [Compiler] Applied actions after repair:")
                    for action in repair_compile_report.actions:
                        print(f"    - {action}")
                _, repaired_rows_raw = execute_sql(db_ref, repaired_sql, engine)
                pred_rows = [tuple(r) for r in repaired_rows_raw]
                pred_row_count = len(pred_rows)
                pred_sql = repaired_sql
                pred_error = None
                valid = True
                repair_status = "attempted_success"
                print("  [Repair] SQL repair succeeded.")
            except Exception as repair_exc:
                pred_error = str(repair_exc)
                valid = False
                repair_status = "attempted_failed"
                print(f"  [Repair] SQL repair failed: {pred_error}")
        else:
            repair_status = "unsupported"

    match = rows_match(gold_rows, pred_rows) if valid and gold_error is None else False

    return {
        "index": item["index"],
        "db": item["db"],
        "question": question,
        "gold_sql": gold_sql,
        "pred_sql": pred_sql,
        "repaired_sql": repaired_sql,
        "repair_status": repair_status,
        "compiler_actions": compiler_actions,
        "valid": valid,
        "match": match,
        "pred_error": pred_error,
        "gold_row_count": gold_row_count,
        "pred_row_count": pred_row_count,
    }


def run_with_timeout(fn, timeout: int) -> dict:
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        executor.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(f"timed out after {timeout}s")
    except Exception:
        executor.shutdown(wait=False)
        raise


def print_live(i: int, total: int, result: dict, correct: int, valid_count: int) -> None:
    status = "MATCH" if result["match"] else ("VALID" if result["valid"] else "ERROR")
    acc = correct / (i + 1) * 100
    print(
        f"  [{i+1:>3}/{total}] {status:<5}  "
        f"gold={result['gold_row_count']} pred={result['pred_row_count']}  "
        f"running EX={acc:.1f}%  — {result['question'][:60]}"
    )


def print_final(results: list[dict], elapsed: float, dataset: str = "", model: str = "", engine: str = "") -> None:
    total = len(results)
    if not total:
        print("No results.")
        return

    correct = sum(1 for r in results if r["match"])
    valid_count = sum(1 for r in results if r["valid"])
    timeouts = sum(1 for r in results if r.get("pred_error") and "timed out" in str(r["pred_error"]))
    near_miss = sum(
        1 for r in results
        if r["valid"] and not r["match"]
        and r["gold_row_count"] is not None
        and r["gold_row_count"] == r["pred_row_count"]
        and r["gold_row_count"] > 0
    )
    exec_times = [r["execution_time_seconds"] for r in results if r.get("execution_time_seconds")]
    avg_time = sum(exec_times) / len(exec_times) if exec_times else 0

    print("\n" + "=" * 55)
    print("  Final Evaluation Summary")
    print("=" * 55)
    if dataset: print(f"  Dataset           : {dataset}")
    if model:   print(f"  Model             : {model}")
    if engine:  print(f"  Engine            : {engine}")
    print(f"  Total questions   : {total}")
    print(f"  Valid SQL Rate    : {valid_count}/{total} ({100*valid_count/total:.1f}%)")
    print(f"  Execution Accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
    print(f"  Near-miss (rows=) : {near_miss}")
    print(f"  Timeouts          : {timeouts}")
    print(f"  Avg time/question : {avg_time:.1f}s")
    print(f"  Total time        : {elapsed:.1f}s")
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(description="NL2Report batch evaluator")
    parser.add_argument("--dataset", required=True, help="Dataset: bird | tpch | m5 | beaver")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model: ollama | anthropic | openai | gemini")
    parser.add_argument("--openai-mode", default="library", choices=["library", "api"],
                        help="OpenAI adapter mode: library uses OPENAI_API_KEY; api uses OpenAI-compatible API env vars")
    parser.add_argument("--questions", required=True, help="Path to questions JSON file")
    parser.add_argument(
        "--output", default=None,
        help="Output JSON path (default: results/<dataset>_<model>_results.json)"
    )
    parser.add_argument("--judge-model", default="openai", choices=["openai", "anthropic", "gemini"],
                        help="LLM judge model to run after result JSON exists")
    parser.add_argument("--judge-openai-mode", default=None, choices=["library", "api"],
                        help="OpenAI mode for the judge. Defaults to --openai-mode.")
    parser.add_argument("--judge-batch-size", type=int, default=5,
                        help="Number of SQL pairs to judge per LLM call")
    parser.add_argument("--judge-output", default=None, help="Judge output JSON path")
    parser.add_argument("--skip-judge", action="store_true", help="Skip automatic LLM judging")
    parser.add_argument("--limit", type=int, default=None, help="Max number of questions to run")
    args = parser.parse_args()

    questions_path = Path(args.questions)
    if not questions_path.exists():
        print(f"Questions file not found: {questions_path}")
        sys.exit(1)

    output_path = Path(args.output) if args.output else Path(f"results/{args.dataset}_{args.model}_results.json")
    judge_openai_mode = args.judge_openai_mode or args.openai_mode
    judge_output_path = Path(args.judge_output) if args.judge_output else None

    questions = load_questions(questions_path)
    if args.limit:
        questions = questions[:args.limit]
    existing = load_existing_results(output_path)

    skipped = len([q for q in questions if q["index"] in existing])
    if skipped:
        print(f"Resuming — skipping {skipped} already completed questions.")

    if result_file_complete(existing, questions):
        print(f"\nResult file is already complete for dataset [{args.dataset}].")
        print(f"No SQL generation needed: {output_path}")
        print_final(list(existing.values()), 0.0)
        if not args.skip_judge:
            run_judge(output_path, args.judge_model, judge_openai_mode, args.judge_batch_size, judge_output_path)
        return

    model = get_model(args.model, args.openai_mode)
    results: list[dict] = list(existing.values())

    total = len(questions)
    correct = sum(1 for r in results if r["match"])
    valid_count = sum(1 for r in results if r["valid"])

    print(f"\nDataset : {args.dataset}")
    print(f"Model   : {args.model}")
    if args.model == "openai":
        print(f"OpenAI  : {args.openai_mode}")
    print(f"Output  : {output_path}")
    print(f"Total   : {total} questions\n")

    global_start = time.time()
    first_schema = load_schema(args.dataset, questions[0]["db"])
    detected_engine = schema_engine(first_schema)

    for item in questions:
        idx = item["index"]
        if idx in existing:
            continue

        db_name = item["db"]
        t_start = time.time()

        try:
            schema = load_schema(args.dataset, db_name)
            schema = apply_vector_filter(
                schema,
                args.dataset,
                db_name,
                item["question"],
                gold_sql=item.get("gold_sql"),
            )
            selected_tables = schema.get("selected_tables") or [t.get("name") for t in schema.get("tables", [])]
            selected_tables = [str(t) for t in selected_tables if t]
            print(f"  [Schema] Tables passed to model ({len(selected_tables)}): {', '.join(selected_tables)}")
            
            engine = schema_engine(schema)
            db_ref = find_database_ref(args.dataset, db_name, schema)

            result = run_with_timeout(
                lambda: process_question(item, args.dataset, model, schema, db_ref, engine),
                QUERY_TIMEOUT,
            )
        except Exception as e:
            result = {
                "index": idx,
                "db": db_name,
                "question": item["question"],
                "gold_sql": item["gold_sql"],
                "pred_sql": None,
                "valid": False,
                "match": False,
                "pred_error": str(e),
                "gold_row_count": None,
                "pred_row_count": None,
            }

        result["execution_time_seconds"] = round(time.time() - t_start, 2)

        results.append(result)
        if result["match"]:
            correct += 1
        if result["valid"]:
            valid_count += 1

        save_results(results, output_path)
        i_done = len(results) - 1
        print_live(i_done, total, result, correct, valid_count)

    print_final(results, time.time() - global_start, dataset=args.dataset, model=args.model, engine=detected_engine)
    print(f"\n  Results saved to {output_path}")
    if not args.skip_judge:
        run_judge(output_path, args.judge_model, judge_openai_mode, args.judge_batch_size, judge_output_path)


if __name__ == "__main__":
    main()
