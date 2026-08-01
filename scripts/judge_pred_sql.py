#!/usr/bin/env python3
"""
Judge predicted SQL against gold SQL using an LLM.

The script reads a result JSON file, sends question/gold_sql/pred_sql plus row
counts to a judge model, and writes per-question scores plus an overall
correctness percent.

Example:
    python scripts/judge_pred_sql.py \
        --input results/beaver_openai_results.json \
        --judge-model openai \
        --openai-mode api \
        --output results/beaver_openai_llm_judged.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))


SYSTEM_PROMPT = (
    "You are a strict SQL evaluation judge. "
    "Compare predicted SQL queries to gold SQL queries for the same natural language questions. "
    "Judge semantic correctness, not formatting. A predicted SQL is correct only if it would answer "
    "the question with the same result as the gold SQL under the evaluated database contents.\n\n"
    "Consider table choice, selected columns, filters, joins, grouping, aggregation, window functions, "
    "ordering, limits, and result grain. Penalize missing filters, extra filters, wrong tables, wrong joins, "
    "wrong aggregation grain, and extra or missing requested output columns. Use gold_row_count and "
    "pred_row_count as strong evidence: if they differ, the SQL cannot be fully correct.\n\n"
    "Return ONLY valid JSON with this schema: "
    "{\"judgments\":[{\"index\": value, \"score\": number, "
    "\"verdict\": \"correct\" | \"partially_correct\" | \"incorrect\", \"reason\": string}]}\n"
    "Use score 1.0 for semantically equivalent SQL, 0.0 for wrong SQL, and a value between 0 and 1 "
    "for partial correctness."
)


def load_results(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Input JSON must be a list of result objects.")
    return data


def make_judge(model_name: str, openai_mode: str):
    if model_name == "openai":
        from models.openai_model import OpenAIModel

        return OpenAIModel(use_api=True)
    if model_name == "anthropic":
        from models.anthropic_model import AnthropicModel

        return AnthropicModel()
    if model_name == "gemini":
        from models.gemini_model import GeminiModel

        return GeminiModel()
    raise ValueError("Unknown judge model. Choose: openai | anthropic | gemini")


def strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(line for line in lines if not line.startswith("```")).strip()
    return raw


def parse_judgment(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(strip_json_fences(raw))
    except json.JSONDecodeError as exc:
        return {
            "score": None,
            "verdict": "parse_error",
            "reason": f"Judge returned invalid JSON: {exc}",
            "raw_judgment": raw,
        }

    if isinstance(parsed, dict) and isinstance(parsed.get("judgments"), list):
        judgments = parsed["judgments"]
        if not judgments or not isinstance(judgments[0], dict):
            return {
                "score": None,
                "verdict": "parse_error",
                "reason": "Judge JSON contained an empty or invalid judgments array.",
                "raw_judgment": raw,
            }
        parsed = judgments[0]

    score = parsed.get("score")
    if not isinstance(score, (int, float)):
        score = None
    elif score < 0:
        score = 0.0
    elif score > 1:
        score = 1.0

    verdict = parsed.get("verdict")
    if verdict not in {"correct", "partially_correct", "incorrect"}:
        verdict = "parse_error"

    return {
        "score": score,
        "verdict": verdict,
        "reason": str(parsed.get("reason", "")).strip(),
    }


def parse_batch_judgments(raw: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(strip_json_fences(raw))
    except json.JSONDecodeError as exc:
        return [{
            "score": None,
            "verdict": "parse_error",
            "reason": f"Judge returned invalid JSON: {exc}",
            "raw_judgment": raw,
        }]

    judgments = parsed.get("judgments") if isinstance(parsed, dict) else parsed
    if not isinstance(judgments, list):
        return [{
            "score": None,
            "verdict": "parse_error",
            "reason": "Judge JSON did not contain a judgments array.",
            "raw_judgment": raw,
        }]

    parsed_judgments = []
    for item in judgments:
        if not isinstance(item, dict):
            parsed_judgments.append({
                "score": None,
                "verdict": "parse_error",
                "reason": "Judgment item is not an object.",
            })
            continue

        score = item.get("score")
        if not isinstance(score, (int, float)):
            score = None
        elif score < 0:
            score = 0.0
        elif score > 1:
            score = 1.0

        verdict = item.get("verdict")
        if verdict not in {"correct", "partially_correct", "incorrect"}:
            verdict = "parse_error"

        parsed_judgments.append({
            "index": item.get("index"),
            "score": score,
            "verdict": verdict,
            "reason": str(item.get("reason", "")).strip(),
        })
    return parsed_judgments


def minimal_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": item.get("index"),
        "question": item.get("question"),
        "gold_sql": item.get("gold_sql"),
        "pred_sql": item.get("pred_sql"),
        "gold_row_count": item.get("gold_row_count"),
        "pred_row_count": item.get("pred_row_count"),
    }


def build_user_prompt(item: dict[str, Any]) -> str:
    return (
        "Question:\n"
        f"{item.get('question', '')}\n\n"
        "Gold SQL:\n"
        f"{item.get('gold_sql', '')}\n\n"
        "Predicted SQL:\n"
        f"{item.get('pred_sql', '')}\n\n"
        "Gold row count:\n"
        f"{item.get('gold_row_count')}\n\n"
        "Predicted row count:\n"
        f"{item.get('pred_row_count')}\n\n"
        "Judge the predicted SQL against the gold SQL. Return only JSON."
    )


def build_batch_user_prompt(items: list[dict[str, Any]]) -> str:
    return (
        "Judge each item in this JSON array. Return one judgment per input item, preserving each index.\n\n"
        f"{json.dumps(items, indent=2, ensure_ascii=False)}"
    )


def judge_item(judge, item: dict[str, Any]) -> dict[str, Any]:
    item_for_judge = minimal_item(item)
    raw = judge._generate(SYSTEM_PROMPT, build_user_prompt(item_for_judge))
    judgment = parse_judgment(raw)
    return {
        **item_for_judge,
        "judge_score": judgment["score"],
        "judge_verdict": judgment["verdict"],
        "judge_reason": judgment["reason"],
        **({"raw_judgment": judgment["raw_judgment"]} if "raw_judgment" in judgment else {}),
    }


def judge_batch(judge, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items_for_judge = [minimal_item(item) for item in items]
    raw = judge._generate(SYSTEM_PROMPT, build_batch_user_prompt(items_for_judge))
    judgments = parse_batch_judgments(raw)
    by_index = {judgment.get("index"): judgment for judgment in judgments}

    judged = []
    for item in items_for_judge:
        judgment = by_index.get(item.get("index"))
        if not judgment:
            judgment = {
                "score": None,
                "verdict": "parse_error",
                "reason": "Judge response did not include this index.",
            }
        judged.append({
            **item,
            "judge_score": judgment["score"],
            "judge_verdict": judgment["verdict"],
            "judge_reason": judgment["reason"],
        })
    return judged


def chunks(items: list[dict[str, Any]], size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def summarize(judged: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [item for item in judged if isinstance(item.get("judge_score"), (int, float))]
    total = len(judged)
    score_sum = sum(float(item["judge_score"]) for item in scored)
    verdict_counts: dict[str, int] = {}
    for item in judged:
        verdict = str(item.get("judge_verdict"))
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

    return {
        "total": total,
        "scored": len(scored),
        "average_score": (score_sum / len(scored)) if scored else 0.0,
        "correctness_percent": (100.0 * score_sum / len(scored)) if scored else 0.0,
        "verdict_counts": verdict_counts,
    }


def judge_results_file(
    input_path: Path,
    output_path: Path | None = None,
    judge_model: str = "openai",
    openai_mode: str = "library",
    limit: int | None = None,
    sleep_seconds: float = 0.0,
    batch_size: int = 5,
) -> dict[str, Any]:
    results = load_results(input_path)
    if limit is not None:
        results = results[:limit]

    final_output_path = output_path or input_path.with_name(f"{input_path.stem}_llm_judged.json")
    judge = make_judge(judge_model, openai_mode)

    judged = []
    batch_size = max(1, batch_size)
    batches = list(chunks(results, batch_size))
    for batch_number, batch in enumerate(batches, 1):
        indexes = ", ".join(str(item.get("index")) for item in batch)
        print(f"[batch {batch_number}/{len(batches)}] Judging indexes={indexes}")
        if batch_size == 1:
            judged.extend(judge_item(judge, item) for item in batch)
        else:
            judged.extend(judge_batch(judge, batch))
        if sleep_seconds and batch_number < len(batches):
            time.sleep(sleep_seconds)

    report = {
        "input": str(input_path),
        "judge_model": judge_model,
        "openai_mode": openai_mode if judge_model == "openai" else None,
        "batch_size": batch_size,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summarize(judged),
        "results": judged,
    }

    final_output_path.parent.mkdir(parents=True, exist_ok=True)
    final_output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["output"] = str(final_output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM judge for predicted SQL result JSON files.")
    parser.add_argument("--input", required=True, type=Path, help="Path to result JSON file.")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON path.")
    parser.add_argument("--judge-model", default="openai", choices=["openai", "anthropic", "gemini"])
    parser.add_argument("--openai-mode", default="library", choices=["library", "api"])
    parser.add_argument("--batch-size", type=int, default=5, help="Number of SQL pairs to judge per LLM call.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of rows to judge.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between judge calls.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = judge_results_file(
        input_path=args.input,
        output_path=args.output,
        judge_model=args.judge_model,
        openai_mode=args.openai_mode,
        limit=args.limit,
        sleep_seconds=args.sleep,
        batch_size=args.batch_size,
    )

    summary = report["summary"]
    print("\nLLM Judge Summary")
    print(f"  Total               : {summary['total']}")
    print(f"  Scored              : {summary['scored']}")
    print(f"  Correctness percent : {summary['correctness_percent']:.2f}%")
    print(f"  Verdict counts      : {summary['verdict_counts']}")
    print(f"  Output              : {report['output']}")


if __name__ == "__main__":
    main()
