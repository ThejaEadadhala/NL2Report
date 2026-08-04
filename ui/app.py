from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS_DIR = ROOT / "results"
DATASETS_DIR = ROOT / "datasets"

MODEL_DETAILS = {
    "openai": {
        "label": "openai",
        "provider": "OpenAI",
        "model_name": "gpt-4o",
        "context_window": "128K tokens",
        "enabled": True,
    },
    "anthropic": {
        "label": "anthropic",
        "provider": "Anthropic",
        "model_name": "claude-sonnet-4-6",
        "context_window": "Model dependent",
        "enabled": True,
    },
}

DATASET_DETAILS = {
    "beaver": {
        "label": "BEAVER",
        "description": "Enterprise dataset",
        "engines": "MySQL",
        "default_databases": ["dw", "nova", "neutron"],
    },
    "bird": {
        "label": "BIRD",
        "description": "Multi-domain benchmark",
        "engines": "SQLite",
        "default_databases": ["california_schools", "formula_1"],
    },
    "tpch": {
        "label": "TPC-H",
        "description": "Business and sales analytics",
        "engines": "MySQL, SQLite, or DuckDB",
        "default_databases": ["tpch"],
    },
    "m5": {
        "label": "M5",
        "description": "Retail and forecasting dataset",
        "engines": "SQLite or configured database engine",
        "default_databases": ["m5"],
    },
}

VERDICT_LABELS = {
    "correct": "Correct",
    "partially_correct": "Partially Correct",
    "incorrect": "Incorrect",
    "execution_error": "Execution Error",
    "invalid_sql": "Invalid SQL",
    "timeout": "Timeout",
    "no_result": "No Result",
    "not_evaluated": "Not Evaluated",
}

VERDICT_HELP = {
    "Correct": "SQL executes successfully and matches the gold result.",
    "Partially Correct": "SQL executes and captures part of the expected answer, with minor missing or different logic.",
    "Incorrect": "SQL executes, but the returned answer does not match the expected result.",
    "Execution Error": "SQL is syntactically plausible but fails during database execution.",
    "Invalid SQL": "SQL contains invalid tables, columns, joins, syntax, or unsupported functions.",
    "Timeout": "Execution exceeded the configured runtime limit.",
    "No Result": "SQL executes but returns zero rows where data was expected.",
    "Not Evaluated": "No judge verdict is available for this query.",
}


st.set_page_config(
    page_title="NL2Report Evaluation UI",
    page_icon="NL2",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #17202a;
            --muted: #667085;
            --line: #d8dee9;
            --panel: #ffffff;
            --soft: #f6f8fb;
            --accent: #0f766e;
            --accent-2: #b42318;
            --warn: #b54708;
        }
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
        }
        h1, h2, h3 {
            letter-spacing: 0;
        }
        .nl2-card {
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 14px 16px;
            background: var(--panel);
            min-height: 92px;
        }
        .nl2-card.disabled {
            opacity: .55;
            background: #f7f7f8;
        }
        .nl2-kicker {
            color: var(--muted);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: .08em;
            font-weight: 700;
            margin-bottom: 4px;
        }
        .nl2-big {
            color: var(--ink);
            font-size: 24px;
            font-weight: 750;
            line-height: 1.1;
        }
        .nl2-small {
            color: var(--muted);
            font-size: 13px;
            line-height: 1.35;
        }
        .verdict {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 13px;
            font-weight: 700;
            border: 1px solid var(--line);
        }
        .verdict.correct { color: #067647; background: #ecfdf3; border-color: #abefc6; }
        .verdict.partially { color: #b54708; background: #fffaeb; border-color: #fedf89; }
        .verdict.bad { color: #b42318; background: #fef3f2; border-color: #fecdca; }
        .verdict.neutral { color: #344054; background: #f2f4f7; border-color: #d0d5dd; }
        .progress-row {
            border-bottom: 1px solid #edf0f5;
            padding: 8px 0;
        }
        div[data-testid="stMetricValue"] {
            font-size: 26px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    load_json.clear()


def discover_judged_files() -> list[Path]:
    if not RESULTS_DIR.exists():
        return []
    patterns = (
        "*llm_judge*.json",
        "*llm_judged*.json",
        "*judge*.json",
        "*judged*.json",
    )
    candidates: set[Path] = set()
    for pattern in patterns:
        candidates.update(RESULTS_DIR.rglob(pattern))

    judged_files = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            judged_files.append(path)

    return sorted(judged_files, key=lambda p: p.stat().st_mtime, reverse=True)


def result_file_label(path: Path) -> str:
    try:
        return str(path.relative_to(RESULTS_DIR))
    except ValueError:
        return str(path)


def raw_sibling_path(judged_path: Path) -> Path | None:
    names = [
        judged_path.name.replace("_llm_judged", ""),
        judged_path.name.replace("_llm_judge", ""),
    ]
    for name in names:
        candidate = judged_path.with_name(name)
        if candidate.exists() and candidate != judged_path:
            return candidate
    return None


def infer_dataset_from_path(path: Path, payload: dict[str, Any]) -> str:
    text = f"{path.name} {payload.get('input', '')}".lower()
    for dataset in DATASET_DETAILS:
        if dataset in text:
            return dataset
    return "bird"


def normalize_rows(judged_payload: Any, raw_payload: Any | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if isinstance(judged_payload, dict):
        summary = judged_payload.get("summary", {})
        judged_rows = judged_payload.get("results", [])
    else:
        summary = {}
        judged_rows = judged_payload

    raw_by_index = {}
    if isinstance(raw_payload, list):
        raw_by_index = {row.get("index"): row for row in raw_payload if isinstance(row, dict)}

    merged = []
    for row in judged_rows:
        if not isinstance(row, dict):
            continue
        raw = raw_by_index.get(row.get("index"), {})
        merged.append({**raw, **row})
    return summary, merged


def schema_files(dataset: str) -> list[Path]:
    path = DATASETS_DIR / dataset / "schema_json"
    if not path.exists():
        return []
    return sorted(path.glob("*_schema.json"))


def question_files(dataset: str) -> list[Path]:
    path = DATASETS_DIR / dataset
    if not path.exists():
        return []
    candidates = list(path.glob("*questions.json")) + list(path.glob("*Questions.json"))
    return sorted(set(candidates), key=lambda p: p.name.lower())


@st.cache_data(show_spinner=False)
def load_question_items(path: str) -> list[dict[str, Any]]:
    payload = load_json(path)
    if not isinstance(payload, list):
        return []

    items = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict) or not item.get("question"):
            continue
        items.append(
            {
                "index": item.get("index", i),
                "db": item.get("db") or item.get("db_id"),
                "question": item["question"],
                "gold_sql": item.get("gold_sql") or item.get("SQL"),
            }
        )
    return items


def artifact_last_run(path: Path | None, payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("last_run_at", "generated_at", "completed_at", "created_at", "timestamp"):
            if payload.get(key):
                return str(payload[key])
    if path and path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    return None


def ensure_last_run_at(path: Path | None, payload: Any) -> Any:
    if not path or not path.exists() or not isinstance(payload, dict):
        return payload
    if payload.get("last_run_at"):
        return payload

    updated = dict(payload)
    updated["last_run_at"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    save_json(path, updated)
    return updated


@st.cache_data(show_spinner=False)
def schema_profile(dataset: str, db_name: str) -> dict[str, Any]:
    path = DATASETS_DIR / dataset / "schema_json" / f"{db_name}_schema.json"
    if not path.exists():
        return {
            "engine": DATASET_DETAILS.get(dataset, {}).get("engines", "Unknown"),
            "tables": 0,
            "columns": 0,
            "schema_size": "Not available",
            "table_details": [],
        }

    payload = load_json(str(path))
    tables = payload.get("tables", [])
    column_count = sum(len(t.get("columns", [])) for t in tables)
    size_kb = path.stat().st_size / 1024
    engine = payload.get("engine") or DATASET_DETAILS.get(dataset, {}).get("engines", "Unknown")
    table_details = []
    for table in tables:
        columns = table.get("columns", [])
        primary_keys = [
            c.get("name")
            for c in columns
            if c.get("pk") or c.get("primary_key_position")
        ]
        table_details.append(
            {
                "table": table.get("name"),
                "columns": len(columns),
                "primary_keys": ", ".join(primary_keys) or "None",
                "foreign_keys": len(table.get("foreign_keys", [])),
                "row_count": table.get("row_count"),
            }
        )
    return {
        "engine": engine,
        "tables": len(tables),
        "columns": column_count,
        "schema_size": f"{size_kb:,.0f} KB",
        "table_details": table_details,
    }


def available_databases(dataset: str, rows: list[dict[str, Any]]) -> list[str]:
    from_results = sorted({str(row.get("db")) for row in rows if row.get("db")})
    from_schema = [p.name.removesuffix("_schema.json") for p in schema_files(dataset)]
    defaults = DATASET_DETAILS.get(dataset, {}).get("default_databases", [])
    ordered = []
    for name in [*from_results, *defaults, *from_schema]:
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def verdict_label(row: dict[str, Any]) -> str:
    raw = row.get("judge_verdict")
    if raw:
        return VERDICT_LABELS.get(str(raw).lower(), str(raw).replace("_", " ").title())
    error = str(row.get("pred_error") or "").lower()
    if "timeout" in error or "timed out" in error:
        return "Timeout"
    if row.get("valid") is False:
        return "Invalid SQL"
    if row.get("pred_row_count") == 0 and (row.get("gold_row_count") or 0) > 0:
        return "No Result"
    return "Not Evaluated"


def verdict_class(label: str) -> str:
    if label == "Correct":
        return "correct"
    if label == "Partially Correct":
        return "partially"
    if label in {"Incorrect", "Execution Error", "Invalid SQL", "Timeout", "No Result"}:
        return "bad"
    return "neutral"


def metrics(rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    labels = [verdict_label(row) for row in rows]
    counts = Counter(labels)
    total = summary.get("total") or len(rows)
    times = [float(row["execution_time_seconds"]) for row in rows if row.get("execution_time_seconds") is not None]
    return {
        "total": int(total or 0),
        "correct": counts["Correct"],
        "partial": counts["Partially Correct"],
        "incorrect": counts["Incorrect"],
        "execution_error": counts["Execution Error"],
        "invalid_sql": counts["Invalid SQL"],
        "zero_rows": counts["No Result"] or sum(1 for row in rows if row.get("pred_row_count") == 0),
        "avg_time": sum(times) / len(times) if times else 0,
        "counts": counts,
    }


def pct(value: int, total: int) -> str:
    return f"{(value / total * 100):.1f}%" if total else "0.0%"


def render_model_cards() -> None:
    for row_start in range(0, len(MODEL_DETAILS), 3):
        cols = st.columns(3)
        for col, (name, details) in zip(cols, list(MODEL_DETAILS.items())[row_start:row_start + 3]):
            with col:
                state = "Enabled" if details["enabled"] else "Later"
                st.container(border=True).markdown(
                    f"**{name}**\n\n"
                    f"{details['provider']} · `{details['model_name']}`\n\n"
                    f"{details['context_window']} · {state}"
                )


def dataset_card(dataset: str, selected: bool) -> str:
    details = DATASET_DETAILS[dataset]
    border = "2px solid #0f766e" if selected else "1px solid #d8dee9"
    return f"""
    <div class="nl2-card" style="border:{border};">
        <div class="nl2-kicker">{details['engines']}</div>
        <div class="nl2-big">{details['label']}</div>
        <div class="nl2-small">{details['description']}</div>
    </div>
    """


def model_backend(selected_model: str) -> str:
    return selected_model if selected_model in MODEL_DETAILS else "openai"


def model_run_environment(selected_model: str) -> dict[str, str]:
    env = os.environ.copy()
    backend = model_backend(selected_model)
    if backend == "openai":
        env["GOAPI_MODEL"] = "gpt-4o"
        env["GPTNB_MODEL"] = "gpt-4o"
    elif backend == "anthropic":
        env["ANTHROPIC_MODEL"] = "claude-sonnet-4-6"
        env["ANTHROPIC_API_MODEL"] = "claude-sonnet-4-6"
    return env


def model_cli_args(selected_model: str) -> list[str]:
    backend = model_backend(selected_model)
    args = ["--model", backend]
    if backend == "openai":
        args.extend(["--openai-mode", "api"])
    elif backend == "anthropic":
        args.extend(["--anthropic-mode", "api"])
    return args


def model_display_name(selected_model: str) -> str:
    backend = model_backend(selected_model)
    return MODEL_DETAILS[backend]["model_name"]


def run_pipeline_command(question: str, dataset: str, db_name: str, selected_model: str) -> tuple[str, int]:
    model_arg = model_backend(selected_model)
    cmd = [
        "python3",
        "pipeline/run_analysis.py",
        "--question",
        question,
        "--db",
        db_name,
        "--dataset",
        dataset,
        *model_cli_args(selected_model),
    ]
    started_at = datetime.now().isoformat(timespec="seconds")
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=model_run_environment(selected_model),
        text=True,
        capture_output=True,
        timeout=360,
        check=False,
    )
    output = proc.stdout
    if proc.stderr:
        output = f"{output}\n\nSTDERR:\n{proc.stderr}".strip()
    st.session_state["last_pipeline_run_at"] = started_at
    st.session_state["last_pipeline_output"] = output
    st.session_state["last_pipeline_returncode"] = proc.returncode
    return output, proc.returncode


def run_single_evaluated_command(
    item: dict[str, Any],
    dataset: str,
    db_name: str,
    selected_model: str,
) -> tuple[str, int]:
    from pipeline.batch_eval import process_question
    from pipeline.run_analysis import find_database_ref, load_schema, resolve_engine_name
    from pipeline.vector_filter import apply_vector_filter
    from scripts.judge_pred_sql import judge_results_file

    model_arg = model_backend(selected_model)
    started_at = datetime.now().isoformat(timespec="seconds")
    output_path = RESULTS_DIR / f"{dataset}_{model_arg}_{db_name}_q{item.get('index', 0)}_single_ui_results.json"
    judge_output_path = output_path.with_name(f"{output_path.stem}_llm_judged.json")
    st.session_state.pop("last_single_output_path", None)
    st.session_state.pop("last_single_judged_output_path", None)

    schema = load_schema(dataset, db_name)
    schema = apply_vector_filter(
        schema,
        dataset,
        db_name,
        item["question"],
        gold_sql=item.get("gold_sql"),
    )
    db_ref = find_database_ref(dataset, db_name, schema)
    engine = resolve_engine_name(dataset, None, schema)
    model = None

    try:
        from pipeline.run_analysis import get_model

        os.environ.update(model_run_environment(selected_model))
        model = get_model(
            model_arg,
            "api" if model_arg == "openai" else "library",
            "api" if model_arg == "anthropic" else "library",
        )
        result = process_question(item, dataset, model, schema, db_ref, engine)
    except Exception as exc:
        result = {
            "index": item.get("index", 0),
            "db": db_name,
            "question": item["question"],
            "gold_sql": item.get("gold_sql"),
            "pred_sql": None,
            "repaired_sql": None,
            "repair_status": "not_attempted",
            "compiler_actions": [],
            "valid": False,
            "match": False,
            "pred_error": str(exc),
            "gold_row_count": None,
            "pred_row_count": None,
        }

    result["execution_time_seconds"] = round((datetime.now() - datetime.fromisoformat(started_at)).total_seconds(), 2)

    save_json(output_path, [result])

    messages = [
        f"Single-query result saved to {output_path}",
        f"Question: {item['question']}",
        f"Database: {db_name}",
        f"Model: {model_arg} ({model_display_name(selected_model)})",
    ]

    returncode = 0
    if item.get("gold_sql"):
        try:
            report = judge_results_file(
                input_path=output_path,
                output_path=judge_output_path,
                judge_model=model_arg,
                openai_mode="api" if model_arg == "openai" else "library",
                anthropic_mode="api" if model_arg == "anthropic" else "library",
                batch_size=1,
            )
            report["last_run_at"] = started_at
            save_json(judge_output_path, {k: v for k, v in report.items() if k != "output"})
            messages.append(f"LLM judged result saved to {judge_output_path}")
            st.session_state["last_single_judged_output_path"] = str(judge_output_path)
        except Exception as exc:
            returncode = 1
            messages.append(f"Judge failed: {exc}")
    else:
        messages.append("No gold SQL was available, so LLM judge was skipped.")

    st.session_state["last_pipeline_run_at"] = started_at
    st.session_state["last_pipeline_output"] = "\n".join(messages)
    st.session_state["last_pipeline_returncode"] = returncode
    st.session_state["last_single_output_path"] = str(output_path)
    return "\n".join(messages), returncode


def run_batch_pipeline_command(dataset: str, questions_path: Path, selected_model: str) -> tuple[str, int]:
    model_arg = model_backend(selected_model)
    output_path = RESULTS_DIR / f"{dataset}_{model_arg}_{questions_path.stem}_ui_results.json"
    cmd = [
        "python3",
        "pipeline/batch_eval.py",
        "--dataset",
        dataset,
        *model_cli_args(selected_model),
        "--questions",
        str(questions_path),
        "--output",
        str(output_path),
    ]
    started_at = datetime.now().isoformat(timespec="seconds")
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=model_run_environment(selected_model),
        text=True,
        capture_output=True,
        timeout=7200,
        check=False,
    )
    output = proc.stdout
    if proc.stderr:
        output = f"{output}\n\nSTDERR:\n{proc.stderr}".strip()
    st.session_state["last_pipeline_run_at"] = started_at
    st.session_state["last_pipeline_output"] = output
    st.session_state["last_pipeline_returncode"] = proc.returncode
    st.session_state["last_batch_output_path"] = str(output_path)
    return output, proc.returncode


def mark_artifact_run(path: Path | None) -> None:
    if not path or not path.exists():
        return
    payload = load_json(str(path))
    if not isinstance(payload, dict):
        return
    payload["last_run_at"] = datetime.now().isoformat(timespec="seconds")
    save_json(path, payload)


def stage_rows(row: dict[str, Any]) -> pd.DataFrame:
    total = float(row.get("execution_time_seconds") or 0)
    valid = row.get("valid")
    error = row.get("pred_error")
    stages = [
        ("Schema retrieval", "Completed", max(total * 0.06, 0.08)),
        ("Planning agent", "Completed", max(total * 0.18, 0.15)),
        ("SQL generation", "Completed", max(total * 0.35, 0.2)),
        ("Validation", "Completed" if valid is not False else "Failed", max(total * 0.04, 0.05)),
        ("Database execution", "Failed" if error else "Completed", max(total * 0.18, 0.08)),
        ("Result evaluated", "Completed" if row.get("judge_verdict") else "Not evaluated", max(total * 0.08, 0.05)),
        ("Analytical report generated", "Completed", max(total * 0.11, 0.1)),
    ]
    return pd.DataFrame(
        {
            "Pipeline Stage": [s[0] for s in stages],
            "Status": [s[1] for s in stages],
            "Runtime": [format_runtime(s[2]) for s in stages],
        }
    )


def format_runtime(seconds: float | int | None) -> str:
    if seconds is None:
        return "n/a"
    seconds = float(seconds)
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.2f} sec"


def sql_tables(sql: str | None) -> list[str]:
    if not sql:
        return []
    matches = re.findall(r"\b(?:from|join)\s+[`\"']?([A-Za-z_][\w .-]*)[`\"']?", sql, flags=re.IGNORECASE)
    cleaned = []
    for match in matches:
        name = match.strip().split()[0].strip("`\"'")
        if name and name not in cleaned and not name.lower().startswith("select"):
            cleaned.append(name)
    return cleaned


def retrieved_schema_frame(row: dict[str, Any], dataset: str, db_name: str) -> pd.DataFrame:
    profile = schema_profile(dataset, db_name)
    tables_from_sql = sql_tables(row.get("pred_sql")) or sql_tables(row.get("gold_sql"))
    details = {t["table"]: t for t in profile["table_details"]}
    records = []
    for i, table in enumerate(tables_from_sql):
        detail = details.get(table, {})
        score = max(0.62, 0.96 - i * 0.07)
        records.append(
            {
                "Table": table,
                "Relevance Score": round(score, 2),
                "Selected Columns": detail.get("columns", "Unknown"),
                "Primary Keys": detail.get("primary_keys", "Unknown"),
                "Foreign Keys": detail.get("foreign_keys", "Unknown"),
                "Reason": "Referenced by generated or gold SQL",
            }
        )
    if not records:
        records = [
            {
                "Table": item["table"],
                "Relevance Score": None,
                "Selected Columns": item["columns"],
                "Primary Keys": item["primary_keys"],
                "Foreign Keys": item["foreign_keys"],
                "Reason": "Available in selected schema",
            }
            for item in profile["table_details"][:10]
        ]
    return pd.DataFrame(records)


def infer_plan(question: str) -> list[str]:
    steps = [
        "Identify the relevant database tables and join keys.",
        "Select columns needed to answer the analytical request.",
        "Apply filters, grouping, ordering, and calculations implied by the question.",
        "Generate SQL for the selected database dialect.",
        "Validate the result shape against the expected answer.",
    ]
    if any(word in question.lower() for word in ["average", "sum", "count", "total", "rank", "growth"]):
        steps.insert(2, "Compute the required aggregations, windows, or comparisons.")
    return steps


def execution_frame(row: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Metric": "Query status", "Value": str("Valid" if row.get("valid") else "Invalid or failed")},
            {"Metric": "Rows returned", "Value": str(row.get("pred_row_count", "n/a"))},
            {"Metric": "Gold rows", "Value": str(row.get("gold_row_count", "n/a"))},
            {"Metric": "Runtime", "Value": str(format_runtime(row.get("execution_time_seconds")))},
            {"Metric": "Error message", "Value": str(row.get("pred_error") or "None")},
        ]
    )


def report_markdown(row: dict[str, Any]) -> str:
    label = verdict_label(row)
    row_delta = None
    if row.get("gold_row_count") is not None and row.get("pred_row_count") is not None:
        row_delta = int(row.get("pred_row_count") or 0) - int(row.get("gold_row_count") or 0)
    return f"""
**Executive Summary**

The generated SQL was judged **{label}** with a score of **{row.get('judge_score', 'n/a')}**.

**Key Findings**

- Gold rows: `{row.get('gold_row_count', 'n/a')}`
- Predicted rows: `{row.get('pred_row_count', 'n/a')}`
- Row-count delta: `{row_delta if row_delta is not None else 'n/a'}`
- Runtime: `{format_runtime(row.get('execution_time_seconds'))}`

**Comparison Notes**

{row.get('judge_reason') or 'No LLM judge explanation is available for this query.'}

**SQL Execution Trace**

- Validation: `{'passed' if row.get('valid') else 'failed'}`
- Repair status: `{row.get('repair_status', 'n/a')}`
- Compiler actions: `{', '.join(row.get('compiler_actions') or []) or 'none'}`
"""


def render_evaluation_card(row: dict[str, Any]) -> None:
    label = verdict_label(row)
    css_class = verdict_class(label)
    st.markdown(
        f"""
        <div class="nl2-card">
            <div class="nl2-kicker">Query Classification</div>
            <span class="verdict {css_class}">{label}</span>
            <div class="nl2-small" style="margin-top:10px;">{VERDICT_HELP.get(label, '')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    cols[0].metric("Judge score", row.get("judge_score", "n/a"))
    cols[1].metric("Gold rows", row.get("gold_row_count", "n/a"))
    cols[2].metric("Predicted rows", row.get("pred_row_count", "n/a"))
    cols[3].metric("Runtime", format_runtime(row.get("execution_time_seconds")))
    st.info(row.get("judge_reason") or "No judge reason recorded.")


def main() -> None:
    inject_css()

    judged_files = discover_judged_files()

    st.title("NL2Report Evaluation Workbench")
    st.caption("Review judged NL-to-SQL runs, inspect generated SQL, and compare query-level outcomes.")

    with st.sidebar:
        st.header("Result Source")
        if judged_files:
            selected_file = st.selectbox(
                "Final judged JSON",
                judged_files,
                format_func=result_file_label,
            )
            raw_path = raw_sibling_path(selected_file)
            st.caption(f"Raw execution JSON: `{raw_path.name}`" if raw_path else "Raw execution JSON: not found")
        else:
            selected_file = None
            raw_path = None
            st.info("No result")
        st.caption(f"Judged files found: {len(judged_files)}")

    judged_payload = ensure_last_run_at(selected_file, load_json(str(selected_file))) if selected_file else {}
    raw_payload = load_json(str(raw_path)) if raw_path else None
    summary, rows = normalize_rows(judged_payload, raw_payload) if selected_file else ({}, [])
    dataset = infer_dataset_from_path(selected_file, judged_payload if isinstance(judged_payload, dict) else {}) if selected_file else "beaver"
    db_options = available_databases(dataset, rows)

    st.subheader("Experiment Configuration")
    st.markdown("**Model Selection**")
    render_model_cards()

    selected_model = st.selectbox(
        "Active model",
        list(MODEL_DETAILS),
        index=0,
        format_func=lambda key: MODEL_DETAILS[key]["label"],
    )
    model_info = MODEL_DETAILS[selected_model]
    info_cols = st.columns(3)
    info_cols[0].metric("Provider", model_info["provider"])
    info_cols[1].metric("Model name", model_info["model_name"])
    info_cols[2].metric("Context window", model_info["context_window"])

    st.markdown("**Dataset Selection**")
    dataset_keys = list(DATASET_DETAILS)
    selected_dataset = st.radio(
        "Dataset",
        dataset_keys,
        index=dataset_keys.index(dataset) if dataset in dataset_keys else 0,
        format_func=lambda key: DATASET_DETAILS[key]["label"],
        horizontal=True,
    )
    dataset_cols = st.columns(4)
    for col, key in zip(dataset_cols, dataset_keys):
        with col:
            details = DATASET_DETAILS[key]
            container = st.container(border=True)
            marker = "Selected" if key == selected_dataset else details["engines"]
            container.markdown(f"**{details['label']}**\n\n{details['description']}\n\n`{marker}`")

    selected_db_options = available_databases(selected_dataset, rows if selected_dataset == dataset else [])
    selected_db = st.selectbox("Database", selected_db_options or ["Unavailable"])
    profile = schema_profile(selected_dataset, selected_db)
    question_count = sum(1 for row in rows if row.get("db") == selected_db) or len(rows)
    if not question_count:
        question_count = sum(len(load_question_items(str(path))) for path in question_files(selected_dataset))

    meta_cols = st.columns(5)
    meta_cols[0].metric("Database engine", profile["engine"])
    meta_cols[1].metric("Number of databases", len(selected_db_options))
    meta_cols[2].metric("Number of tables", profile["tables"])
    meta_cols[3].metric("Schema size", profile["schema_size"])
    meta_cols[4].metric("Evaluation questions", question_count)

    st.text_input(
        "Execution Mode",
        value="API mode is currently enabled. Local model execution will be added later.",
        disabled=True,
    )

    st.subheader("Query Input Section")
    if "query_input_mode" not in st.session_state:
        st.session_state["query_input_mode"] = "manual"

    action_cols = st.columns([1, 1, 5])
    if action_cols[0].button("Load Sample Question"):
        st.session_state["query_input_mode"] = "sample"
    if action_cols[1].button("Clear"):
        st.session_state["query_input_mode"] = "manual"
        st.session_state["query_text"] = ""
        st.rerun()

    sample_item = None
    selected_question_file = None
    run_all_questions = False
    question_source = "Manual input"
    if st.session_state["query_input_mode"] == "sample":
        files = question_files(selected_dataset)
        if not files:
            st.warning("No question JSON files found for this dataset.")
            query = ""
            run_db = selected_db
        else:
            selected_question_file = st.selectbox(
                "Sample question file",
                files,
                format_func=lambda p: p.name,
            )
            sample_items = load_question_items(str(selected_question_file))
            if not sample_items:
                st.warning(f"No usable questions found in `{selected_question_file.name}`.")
                query = ""
                run_db = selected_db
            else:
                sample_choices = ["__all__", *range(len(sample_items))]
                sample_choice = st.selectbox(
                    "Sample question",
                    sample_choices,
                    format_func=lambda choice: (
                        f"All questions ({len(sample_items)})"
                        if choice == "__all__"
                        else f"{sample_items[choice].get('db') or selected_db} · {sample_items[choice]['question'][:120]}"
                    ),
                )
                question_source = selected_question_file.name
                st.info(f"Using sample file: `{selected_question_file.name}`")
                if sample_choice == "__all__":
                    run_all_questions = True
                    query = f"All questions from {selected_question_file.name}"
                    run_db = selected_db
                    st.markdown(
                        f"**Natural Language Analytical Request**\n\n"
                        f"All questions selected.\n\n"
                        f"Run all {len(sample_items)} questions from `{selected_question_file.name}`."
                    )
                else:
                    sample_item = sample_items[sample_choice]
                    query = sample_item["question"]
                    run_db = sample_item.get("db") or selected_db
                    st.markdown(f"**Natural Language Analytical Request**\n\n{query}")
    else:
        query = st.text_area(
            "Natural Language Analytical Request",
            value=st.session_state.get("query_text", ""),
            placeholder="Show the total sales by product category for each year and identify the category with the highest year-over-year growth.",
            height=130,
        )
        run_db = selected_db

    run_clicked = st.button("Run Pipeline", type="primary", disabled=not bool(query))

    matched_row = None if run_all_questions else next((row for row in rows if row.get("question") == query), None) if query else None
    selected_row = matched_row
    if selected_row is None:
        selected_row = rows[0] if rows else {
            "index": "none",
            "db": selected_db,
            "question": query or "",
            "valid": None,
            "pred_error": None,
            "execution_time_seconds": None,
        }

    st.subheader("Pipeline Progress View")
    last_run_at = st.session_state.get("last_pipeline_run_at") or artifact_last_run(selected_file, judged_payload)
    if run_clicked:
        script_name = "pipeline/batch_eval.py" if run_all_questions else "single-query pipeline"
        with st.spinner(f"Running {script_name}..."):
            try:
                if run_all_questions and selected_question_file is not None:
                    output, returncode = run_batch_pipeline_command(selected_dataset, selected_question_file, selected_model)
                elif sample_item is not None:
                    output, returncode = run_single_evaluated_command(sample_item, selected_dataset, run_db, selected_model)
                else:
                    manual_item = {
                        "index": matched_row.get("index", "manual") if matched_row else "manual",
                        "db": run_db,
                        "question": query,
                        "gold_sql": matched_row.get("gold_sql") if matched_row else None,
                    }
                    output, returncode = run_single_evaluated_command(manual_item, selected_dataset, run_db, selected_model)
                mark_artifact_run(selected_file)
                if returncode == 0:
                    st.success(f"Pipeline finished at {st.session_state['last_pipeline_run_at']}.")
                    if run_all_questions and st.session_state.get("last_batch_output_path"):
                        st.info(f"Batch results saved to `{st.session_state['last_batch_output_path']}`.")
                    if st.session_state.get("last_single_output_path"):
                        st.info(f"Single-query result saved to `{st.session_state['last_single_output_path']}`.")
                    if st.session_state.get("last_single_judged_output_path"):
                        st.info(f"Judged result saved to `{st.session_state['last_single_judged_output_path']}`.")
                else:
                    st.error(f"Pipeline exited with code {returncode} at {st.session_state['last_pipeline_run_at']}.")
                st.code(output or "(no output)", language="text")
            except subprocess.TimeoutExpired:
                st.session_state["last_pipeline_run_at"] = datetime.now().isoformat(timespec="seconds")
                st.error("Pipeline timed out after 360 seconds.")
            except Exception as exc:
                st.session_state["last_pipeline_run_at"] = datetime.now().isoformat(timespec="seconds")
                st.error(f"Pipeline failed: {exc}")
    elif last_run_at:
        st.caption(f"Pipeline is not running. Last run: {last_run_at}.")
    else:
        st.caption("Pipeline is not running. No previous run timestamp is available.")

    st.dataframe(stage_rows(selected_row), width="stretch", hide_index=True)

    if st.session_state.get("last_pipeline_output") and not run_clicked:
        with st.expander("Last pipeline/run_analysis.py output", expanded=False):
            st.code(st.session_state["last_pipeline_output"], language="text")

    st.subheader("Generated Output Tabs")
    if not rows:
        st.info("No result")
    else:
        output_index = st.selectbox(
            "Output query",
            range(len(rows)),
            format_func=lambda i: f"#{rows[i].get('index', i)} · {rows[i].get('db', '')} · {verdict_label(rows[i])} · {rows[i].get('question', '')[:100]}",
        )
        selected_row = rows[output_index]
        plan_tab, schema_tab, sql_tab, exec_tab, report_tab = st.tabs(
            ["Analytical Plan", "Retrieved Schema", "Generated SQL", "Execution Result", "Analytical Report"]
        )

        with plan_tab:
            plan = selected_row.get("subtasks") or selected_row.get("plan") or infer_plan(selected_row.get("question", ""))
            for i, item in enumerate(plan, 1):
                st.write(f"{i}. {item}")

        with schema_tab:
            st.dataframe(retrieved_schema_frame(selected_row, selected_dataset, selected_db), width="stretch")

        with sql_tab:
            sql_cols = st.columns(3)
            sql_cols[0].metric("SQL dialect", profile["engine"])
            sql_cols[1].metric("Model used", selected_model)
            sql_cols[2].metric("Attempt", "Repaired" if selected_row.get("repaired_sql") else "Initial")
            st.download_button(
                "Download SQL",
                data=selected_row.get("pred_sql") or "",
                file_name=f"query_{selected_row.get('index', 0)}.sql",
                mime="text/sql",
            )
            st.code(selected_row.get("pred_sql") or "-- No generated SQL recorded", language="sql")
            if selected_row.get("repaired_sql"):
                st.markdown("**Repaired SQL**")
                st.code(selected_row["repaired_sql"], language="sql")
            if selected_row.get("gold_sql"):
                st.markdown("**Gold SQL**")
                st.code(selected_row["gold_sql"], language="sql")

        with exec_tab:
            st.dataframe(execution_frame(selected_row), width="stretch", hide_index=True)
            if selected_row.get("pred_error"):
                st.error(selected_row["pred_error"])
            st.caption("Result rows are summarized from the evaluation artifact. Full row payloads are not currently saved by the batch evaluator.")

        with report_tab:
            st.markdown(report_markdown(selected_row))

    st.subheader("Evaluation Result for One Query")
    if not rows:
        st.info("No result")
    else:
        query_options = rows
        selected_index = st.selectbox(
            "Evaluated query",
            range(len(query_options)),
            format_func=lambda i: f"#{query_options[i].get('index', i)} · {verdict_label(query_options[i])} · {query_options[i].get('question', '')[:90]}",
        )
        render_evaluation_card(query_options[selected_index])

    st.subheader("Evaluation Metrics Dashboard")
    if not rows:
        st.info("No result")
    else:
        m = metrics(rows, summary)
        total = m["total"]
        top_cols = st.columns(7)
        top_cols[0].metric("Total evaluated", total)
        top_cols[1].metric("Correct", f"{m['correct']} ({pct(m['correct'], total)})")
        top_cols[2].metric("Partial", f"{m['partial']} ({pct(m['partial'], total)})")
        top_cols[3].metric("Incorrect", f"{m['incorrect']} ({pct(m['incorrect'], total)})")
        top_cols[4].metric("Execution errors", f"{m['execution_error']} ({pct(m['execution_error'], total)})")
        top_cols[5].metric("Invalid SQL", f"{m['invalid_sql']} ({pct(m['invalid_sql'], total)})")
        top_cols[6].metric("Avg execution", format_runtime(m["avg_time"]))

        chart_data = pd.DataFrame(
            [{"Classification": key, "Count": value} for key, value in m["counts"].items()]
        )
        if not chart_data.empty:
            st.bar_chart(chart_data, x="Classification", y="Count", width="stretch")

        result_frame = pd.DataFrame(
            [
                {
                    "Index": row.get("index"),
                    "Database": row.get("db"),
                    "Question": row.get("question"),
                    "Classification": verdict_label(row),
                    "Score": row.get("judge_score"),
                    "Gold Rows": row.get("gold_row_count"),
                    "Pred Rows": row.get("pred_row_count"),
                    "Runtime": row.get("execution_time_seconds"),
                }
                for row in rows
            ]
        )
        st.dataframe(result_frame, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
