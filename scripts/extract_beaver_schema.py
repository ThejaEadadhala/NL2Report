#!/usr/bin/env python3
"""Extract BEAVER MySQL/table metadata as pipeline-compatible schema JSON."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DUMP_DATABASES = ("dw", "neutron", "nova")
DEFAULT_DUMP_DIR = Path("datasets/beaver/databases")
DEFAULT_SCHEMA_DIR = Path("datasets/beaver/schema_json")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def mysql_connect(database: str | None = None) -> Any:
    try:
        import mysql.connector
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency `mysql-connector-python`. "
            "Install it with: python3 -m pip install mysql-connector-python"
        ) from exc

    config: dict[str, Any] = {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", "Root@1234"),
    }
    if database:
        config["database"] = database
    return mysql.connector.connect(**config)


def find_mysql_binary(mysql_bin: str | None = None) -> str:
    candidates = [
        mysql_bin,
        os.getenv("MYSQL_BIN"),
        shutil.which("mysql"),
        "/usr/local/mysql/bin/mysql",
        "/opt/homebrew/bin/mysql",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise SystemExit(
        "mysql CLI binary not found. Install MySQL client or set MYSQL_BIN, "
        "for example: MYSQL_BIN=/usr/local/mysql/bin/mysql"
    )


def mysql_cli_auth_args() -> list[str]:
    args = [
        f"--host={os.getenv('MYSQL_HOST', '127.0.0.1')}",
        f"--port={os.getenv('MYSQL_PORT', '3306')}",
        f"--user={os.getenv('MYSQL_USER', 'root')}",
    ]
    password = os.getenv("MYSQL_PASSWORD", "Root@1234")
    if password:
        args.append(f"--password={password}")
    return args


def expected_dump_paths(dump_dir: Path, databases: Iterable[str]) -> list[Path]:
    return [dump_dir / f"{database}.sql" for database in databases]


def validate_dump_paths(dump_paths: list[Path]) -> None:
    missing = [str(path) for path in dump_paths if not path.exists()]
    if missing:
        raise SystemExit("Missing BEAVER SQL dump file(s):\n  " + "\n  ".join(missing))


def import_mysql_dumps(dump_dir: Path, databases: Iterable[str], mysql_bin: str | None = None) -> None:
    dump_paths = expected_dump_paths(dump_dir, databases)
    validate_dump_paths(dump_paths)
    mysql = find_mysql_binary(mysql_bin)
    auth_args = mysql_cli_auth_args()

    for dump_path in dump_paths:
        print(f"Importing {dump_path}...")
        with dump_path.open("rb") as dump_file:
            completed = subprocess.run(
                [mysql, *auth_args],
                stdin=dump_file,
                check=False,
            )
        if completed.returncode != 0:
            raise SystemExit(
                f"Import failed for {dump_path} with exit code {completed.returncode}."
            )


def fetch_all_dicts(connection: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return list(cursor.fetchall())
    finally:
        cursor.close()


def get_mysql_row_count(connection: Any, table_name: str) -> int | None:
    cursor = connection.cursor()
    quoted = "`" + table_name.replace("`", "``") + "`"
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {quoted}")
        return int(cursor.fetchone()[0])
    except Exception:
        return None
    finally:
        cursor.close()


def get_mysql_foreign_keys(connection: Any, database: str) -> list[dict[str, Any]]:
    rows = fetch_all_dicts(
        connection,
        """
        SELECT
          kcu.CONSTRAINT_NAME,
          kcu.ORDINAL_POSITION,
          kcu.TABLE_NAME,
          kcu.COLUMN_NAME,
          kcu.REFERENCED_TABLE_NAME,
          kcu.REFERENCED_COLUMN_NAME,
          rc.UPDATE_RULE,
          rc.DELETE_RULE
        FROM information_schema.KEY_COLUMN_USAGE AS kcu
        LEFT JOIN information_schema.REFERENTIAL_CONSTRAINTS AS rc
          ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
         AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
        WHERE kcu.TABLE_SCHEMA = %s
          AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY kcu.TABLE_NAME, kcu.CONSTRAINT_NAME, kcu.ORDINAL_POSITION
        """,
        (database,),
    )
    return [
        {
            "id": row["CONSTRAINT_NAME"],
            "sequence": row["ORDINAL_POSITION"] - 1,
            "from_table": row["TABLE_NAME"],
            "from_column": row["COLUMN_NAME"],
            "to_table": row["REFERENCED_TABLE_NAME"],
            "to_column": row["REFERENCED_COLUMN_NAME"],
            "on_update": row.get("UPDATE_RULE"),
            "on_delete": row.get("DELETE_RULE"),
            "match": None,
        }
        for row in rows
    ]


def extract_mysql_schema(database: str, include_row_counts: bool) -> dict[str, Any]:
    connection = mysql_connect(database)
    try:
        table_rows = fetch_all_dicts(
            connection,
            """
            SELECT TABLE_NAME, TABLE_TYPE
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
            """,
            (database,),
        )
        column_rows = fetch_all_dicts(
            connection,
            """
            SELECT
              TABLE_NAME,
              ORDINAL_POSITION,
              COLUMN_NAME,
              COLUMN_TYPE,
              IS_NULLABLE,
              COLUMN_DEFAULT,
              COLUMN_KEY,
              COLUMN_COMMENT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, ORDINAL_POSITION
            """,
            (database,),
        )
        all_foreign_keys = get_mysql_foreign_keys(connection, database)

        columns_by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in column_rows:
            columns_by_table[row["TABLE_NAME"]].append(
                {
                    "cid": row["ORDINAL_POSITION"] - 1,
                    "name": row["COLUMN_NAME"],
                    "type": row["COLUMN_TYPE"] or "",
                    "not_null": row["IS_NULLABLE"] == "NO",
                    "default": row["COLUMN_DEFAULT"],
                    "primary_key_position": 1 if row["COLUMN_KEY"] == "PRI" else 0,
                    "beaver_description": {
                        "semantic_name": "",
                        "description": row.get("COLUMN_COMMENT") or "",
                        "data_format": row["COLUMN_TYPE"] or "",
                        "value_description": "",
                    },
                }
            )

        foreign_keys_by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for foreign_key in all_foreign_keys:
            foreign_keys_by_table[foreign_key["from_table"]].append(foreign_key)

        tables = []
        for row in table_rows:
            table_name = row["TABLE_NAME"]
            tables.append(
                {
                    "name": table_name,
                    "type": row["TABLE_TYPE"].lower().replace(" ", "_"),
                    "create_sql": "",
                    "row_count": get_mysql_row_count(connection, table_name)
                    if include_row_counts
                    else None,
                    "columns": columns_by_table.get(table_name, []),
                    "foreign_keys": foreign_keys_by_table.get(table_name, []),
                }
            )

        return {
            "db_id": database,
            "engine": "mysql",
            "mysql_database": database,
            "source": "mysql-information-schema",
            "tables": tables,
            "foreign_keys": all_foreign_keys,
        }
    finally:
        connection.close()


def build_llm_prompt(schema: dict[str, Any], question: str | None = None) -> str:
    question_text = question or "<USER_QUESTION_HERE>"
    schema_json = json.dumps(schema, indent=2, ensure_ascii=False)
    return f"""You are an expert MySQL text-to-SQL assistant.
Use only the tables, columns, primary keys, and foreign keys in this schema JSON.
Return one valid read-only MySQL SELECT query and no extra explanation.

Schema JSON:
```json
{schema_json}
```

Question:
{question_text}
"""


def write_json(data: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_schema_outputs(
    schemas: list[dict[str, Any]],
    output: Path,
    prompt_output: Path | None,
    question: str | None,
) -> None:
    extracting_multiple = len(schemas) > 1

    for schema in schemas:
        if extracting_multiple or output.suffix.lower() != ".json":
            output_path = output / f"{schema['db_id']}_schema.json"
        else:
            output_path = output
        write_json(schema, output_path)

        if prompt_output:
            prompt = build_llm_prompt(schema, question)
            if extracting_multiple or prompt_output.suffix.lower() != ".txt":
                prompt_path = prompt_output / f"{schema['db_id']}_prompt.txt"
            else:
                prompt_path = prompt_output
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(prompt, encoding="utf-8")

    if extracting_multiple:
        write_json(
            [
                {
                    "db_id": schema["db_id"],
                    "engine": schema.get("engine", "mysql"),
                    "mysql_database": schema.get("mysql_database", schema["db_id"]),
                    "table_count": len(schema["tables"]),
                    "foreign_key_count": len(schema.get("foreign_keys", [])),
                    "schema_json": str(output / f"{schema['db_id']}_schema.json"),
                }
                for schema in schemas
            ],
            output / "all_beaver_schemas_index.json",
        )


def parse_args() -> argparse.Namespace:
    load_env_file(Path(".env"))
    parser = argparse.ArgumentParser(
        description=(
            "Import BEAVER SQL dumps into MySQL and extract table, column, "
            "and foreign-key metadata as schema JSON."
        )
    )
    parser.add_argument(
        "--mysql-database",
        action="append",
        help=(
            "Live MySQL database/schema name to introspect. Repeat for multiple "
            "databases. Without --skip-import, matching <database>.sql dumps are "
            "imported first."
        ),
    )
    parser.add_argument(
        "--dump-dir",
        type=Path,
        default=DEFAULT_DUMP_DIR,
        help="Directory containing BEAVER SQL dumps. Defaults to datasets/beaver/databases.",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Skip SQL dump import and only introspect existing MySQL databases.",
    )
    parser.add_argument(
        "--mysql-bin",
        help="Path to mysql CLI binary. Defaults to MYSQL_BIN, PATH mysql, or common install paths.",
    )
    parser.add_argument(
        "--include-row-counts",
        action="store_true",
        help="For live MySQL extraction, run COUNT(*) on every table.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SCHEMA_DIR,
        help="Output JSON file for one DB, or output directory for multiple DBs.",
    )
    parser.add_argument(
        "--prompt-output",
        type=Path,
        help="Optional prompt file for one DB, or prompt output directory for multiple DBs.",
    )
    parser.add_argument(
        "--question",
        help="Optional natural-language question to include in generated prompt files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    databases = args.mysql_database or list(DEFAULT_DUMP_DATABASES)
    if not args.skip_import:
        import_mysql_dumps(args.dump_dir, databases, args.mysql_bin)
    schemas = [
        extract_mysql_schema(database, args.include_row_counts)
        for database in databases
    ]

    if not schemas:
        raise SystemExit("No BEAVER schemas were extracted.")

    write_schema_outputs(schemas, args.output, args.prompt_output, args.question)
    print(f"Extracted {len(schemas)} BEAVER schema(s).")
    print(f"Schema output: {args.output}")
    if args.prompt_output:
        print(f"Prompt output: {args.prompt_output}")


if __name__ == "__main__":
    main()
