"""
run_analysis.py
Main pipeline entry point.

Usage:
    python pipeline/run_analysis.py \
        --question "How many schools are in Alameda county?" \
        --db california_schools \
        --dataset bird \
        --split dev

    python pipeline/run_analysis.py \
        --question "What is the total revenue by order quarter?" \
        --db tpch \
        --dataset tpch \
        --model ollama

    python pipeline/run_analysis.py \
        --question "Who won the most races?" \
        --db formula_1 \
        --dataset bird \
        --split dev \
        --model ollama
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import schema_path, DEFAULT_MODEL
from pipeline.planning_agent import PlanningAgent
from pipeline.vector_filter import apply_vector_filter

FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(ALTER|ATTACH|CREATE|DELETE|DETACH|DROP|INSERT|PRAGMA|REINDEX|REPLACE|UPDATE|VACUUM)\b",
    re.IGNORECASE,
)


# ── Model factory ──────────────────────────────────────────────────────────────

def get_model(model_name: str, openai_mode: str = "library", anthropic_mode: str = "library"):
    if model_name == "ollama":
        from models.ollama_model import OllamaModel
        return OllamaModel()
    elif model_name == "openai":
        from models.openai_model import OpenAIModel
        return OpenAIModel(use_api=openai_mode == "api")
    elif model_name == "anthropic":
        from models.anthropic_model import AnthropicModel
        return AnthropicModel(use_api=anthropic_mode == "api")
    elif model_name == "gemini":
        from models.gemini_model import GeminiModel
        return GeminiModel()
    elif model_name == 'goapi':
        from models.goapi_model import GoAPIModel
        return GoAPIModel()
    else:
        raise ValueError(f"Unknown model '{model_name}'. Choose: ollama | openai | anthropic | gemini")


# ── Engine factory ─────────────────────────────────────────────────────────────

def load_engine_config() -> dict:
    path = Path("config/engine_config.json")
    if path.exists():
        return json.loads(path.read_text())
    return {}


def resolve_engine_name(dataset: str, cli_engine: str | None, schema: dict) -> str:
    """Return the engine name to use. MySQL schemas always use 'mysql'."""
    if schema_engine(schema) == "mysql":
        return "mysql"
    if cli_engine:
        return cli_engine
    ds_cfg = load_engine_config().get(dataset, "sqlite")
    if isinstance(ds_cfg, dict):
        return ds_cfg.get("engine", "sqlite")
    return ds_cfg


def get_engine(engine_name: str, dataset: str, db_path: Path):
    """Return an engine instance for sqlite or duckdb. Returns None for mysql (handled separately)."""
    if engine_name == "sqlite":
        from engines.sqlite_engine import SQLiteEngine
        return SQLiteEngine(db_path)
    elif engine_name == "duckdb":
        from engines.duckdb_engine import DuckDBEngine
        return DuckDBEngine(dataset=dataset)
    return None


# ── Schema / DB helpers ────────────────────────────────────────────────────────

def load_schema(dataset: str, db_name: str) -> dict:
    path = schema_path(dataset, db_name)
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    return json.loads(path.read_text())


def find_db_path(dataset: str, db_name: str) -> Path:
    base = Path("datasets") / dataset
    matches = list(base.rglob(f"{db_name}.sqlite"))
    if not matches:
        raise FileNotFoundError(f"No SQLite file found for '{db_name}' under {base}")
    return matches[0]


def schema_engine(schema: dict) -> str:
    return schema.get("engine", "sqlite")


def find_database_ref(dataset: str, db_name: str, schema: dict) -> Path | str:
    if schema_engine(schema) == "mysql":
        return schema.get("mysql_database") or schema.get("db_id") or db_name
    base = Path("datasets") / dataset
    for suffix in (".duckdb", ".sqlite"):
        matches = list(base.rglob(f"{db_name}{suffix}"))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"No database file found for '{db_name}' under {base}")


# ── MySQL execution (Beaver) ───────────────────────────────────────────────────

def mysql_connect(database: str):
    try:
        import mysql.connector
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `mysql-connector-python`. "
            "Install requirements or run: python3 -m pip install mysql-connector-python"
        ) from exc
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=database,
    )


def normalize_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def validate_read_only_sql(sql: str) -> str:
    stripped = sql.strip().rstrip(";")
    first_word = stripped.split(None, 1)[0].upper() if stripped else ""
    if first_word not in {"SELECT", "WITH"}:
        raise ValueError("Only SELECT or WITH statements are allowed.")
    if ";" in stripped or FORBIDDEN_SQL_PATTERN.search(stripped):
        raise ValueError("Only one read-only SQL statement is allowed.")
    return stripped


def execute_sqlite(db_path: Path, sql: str) -> tuple[list, list]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(sql)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    conn.close()
    return columns, [list(r) for r in rows]


def execute_mysql(database: str, sql: str) -> tuple[list, list]:
    conn = mysql_connect(database)
    cursor = conn.cursor()
    try:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return columns, [[normalize_value(v) for v in row] for row in rows]
    finally:
        cursor.close()
        conn.close()


def execute_sql(database_ref: Path | str, sql: str, engine: str) -> tuple[list, list]:
    sql = validate_read_only_sql(sql)
    if engine == "mysql":
        return execute_mysql(str(database_ref), sql)
    if engine == "duckdb":
        import duckdb
        conn = duckdb.connect(str(database_ref), read_only=True)
        try:
            result = conn.execute(sql)
            rows = result.fetchall()
            columns = [desc[0] for desc in result.description] if result.description else []
            return columns, [list(r) for r in rows]
        finally:
            conn.close()
    return execute_sqlite(Path(database_ref), sql)


# ── Output ─────────────────────────────────────────────────────────────────────

def print_results(columns: list, rows: list) -> None:
    if not rows:
        print("(no results)")
        return
    col_widths = [max(len(str(c)), max((len(str(r[i])) for r in rows), default=0))
                  for i, c in enumerate(columns)]
    header = " | ".join(str(c).ljust(w) for c, w in zip(columns, col_widths))
    print(header)
    print("-" * len(header))
    for row in rows[:50]:
        print(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
    if len(rows) > 50:
        print(f"... ({len(rows)} rows total, showing first 50)")


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run(question: str, dataset: str, db_name: str, split: str, model_name: str,
        openai_mode: str = "library",
        anthropic_mode: str = "library",
        cli_engine: str | None = None) -> None:

    schema = load_schema(dataset, db_name)
    schema = apply_vector_filter(schema, dataset, db_name, question)
    model = get_model(model_name, openai_mode, anthropic_mode)
    db_schema_engine = schema_engine(schema)
    database_ref = find_database_ref(dataset, db_name, schema)
    engine_name = resolve_engine_name(dataset, cli_engine, schema)

    print(f"\nQuestion : {question}")
    print(f"Database : {db_name} ({dataset}/{split})")
    print(f"Model    : {model_name}")
    if model_name == "openai":
        print(f"OpenAI   : {openai_mode}")
    if model_name == "anthropic":
        print(f"Anthropic: {anthropic_mode}")
    print(f"Engine   : {engine_name}\n")

    # Build a unified execute callable
    if db_schema_engine == "mysql":
        def do_execute(sql: str) -> tuple[list, list, str | None]:
            try:
                sql = validate_read_only_sql(sql)
                cols, rows = execute_mysql(str(database_ref), sql)
                return cols, rows, None
            except Exception as e:
                return [], [], str(e)
    else:
        engine_obj = get_engine(engine_name, dataset, database_ref)

        def do_execute(sql: str) -> tuple[list, list, str | None]:
            return engine_obj.execute_sql(sql)

    if dataset == "beaver":
        print("Planning bypassed for Beaver test run.")
        subtasks = [question]
    else:
        print("Planning...")
        subtasks = PlanningAgent(model).plan(question, schema)

    if len(subtasks) == 1:
        print("Generating SQL...")
        sql = model.generate_sql(subtasks[0], schema)
        print(f"\nSQL:\n{sql}\n")
        print("Executing...")
        columns, rows, error = do_execute(sql)
        if error:
            print(f"Error: {error}")
        else:
            print(f"\nResults ({len(rows)} rows):")
            print_results(columns, rows)
    else:
        print(f"Plan ({len(subtasks)} subtasks):")
        for i, task in enumerate(subtasks, 1):
            print(f"  {i}. {task}")

        for i, task in enumerate(subtasks, 1):
            print(f"\n--- Subtask {i}: {task} ---")
            print("Generating SQL...")
            sql = model.generate_sql(task, schema)
            print(f"\nSQL:\n{sql}\n")
            print("Executing...")
            columns, rows, error = do_execute(sql)
            if error:
                print(f"Error: {error}")
            else:
                print(f"\nResults ({len(rows)} rows):")
                print_results(columns, rows)


def main():
    parser = argparse.ArgumentParser(description="NL2Report pipeline")
    parser.add_argument("--question", required=True, help="Natural language question")
    parser.add_argument("--db", required=True, help="Database name (e.g. california_schools)")
    parser.add_argument("--dataset", default="bird", help="Dataset (default: bird)")
    parser.add_argument("--split", default="", help="Split: train | dev (auto-detected if omitted)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Model: ollama | openai | anthropic | gemini (default: ollama)")
    parser.add_argument("--openai-mode", default="library", choices=["library", "api"],
                        help="OpenAI adapter mode: library uses OPENAI_API_KEY; api uses OpenAI-compatible API env vars")
    parser.add_argument("--anthropic-mode", default="library", choices=["library", "api"],
                        help="Anthropic adapter mode: library uses the Anthropic SDK; api uses OpenAI-compatible API env vars")
    parser.add_argument("--engine", default=None, choices=["sqlite", "duckdb"],
                        help="Execution engine (default: from config/engine_config.json)")
    args = parser.parse_args()

    run(args.question, args.dataset, args.db, args.split, args.model, args.openai_mode, args.anthropic_mode, args.engine)


if __name__ == "__main__":
    main()
