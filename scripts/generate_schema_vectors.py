#!/usr/bin/env python3
"""Generate schema_vector JSON files and retrieve top matching schema tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_DIMENSION = 384
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in TOKEN_PATTERN.findall(text.lower()):
        tokens.extend(part for part in raw_token.split("_") if part)
        tokens.append(raw_token)
    return tokens


def token_hash(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False)


def embed_text(text: str, dimension: int = DEFAULT_DIMENSION) -> list[float]:
    token_counts = Counter(tokenize(text))
    return embed_tokens(token_counts, {token: 1.0 for token in token_counts}, dimension)


def embed_tokens(
    token_counts: Counter[str],
    idf: dict[str, float],
    dimension: int = DEFAULT_DIMENSION,
) -> list[float]:
    vector = [0.0] * dimension
    for token, count in token_counts.items():
        hashed = token_hash(token)
        index = hashed % dimension
        sign = 1.0 if ((hashed >> 8) & 1) else -1.0
        vector[index] += sign * count * idf.get(token, 0.0)

    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [round(value / norm, 8) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def column_description(column: dict[str, Any]) -> str:
    beaver_description = column.get("beaver_description") or {}
    return " ".join(
        str(value)
        for value in (
            column.get("name", ""),
            column.get("type", ""),
            column.get("description", ""),
            beaver_description.get("semantic_name", ""),
            beaver_description.get("description", ""),
            beaver_description.get("data_format", ""),
            beaver_description.get("value_description", ""),
        )
        if value
    )


def table_text(table: dict[str, Any]) -> str:
    parts = [
        str(table.get("name", "")),
        str(table.get("type", "")),
        str(table.get("create_sql", "")),
    ]
    parts.extend(column_description(column) for column in table.get("columns", []))
    for foreign_key in table.get("foreign_keys", []):
        parts.append(
            " ".join(
                str(value)
                for value in (
                    foreign_key.get("from"),
                    foreign_key.get("from_column"),
                    foreign_key.get("to_table"),
                    foreign_key.get("to_col"),
                    foreign_key.get("to_column"),
                )
                if value
            )
        )
    return " ".join(part for part in parts if part)


def build_idf(table_texts: list[str]) -> dict[str, float]:
    document_count = len(table_texts)
    document_frequency: Counter[str] = Counter()
    for text in table_texts:
        document_frequency.update(set(tokenize(text)))
    return {
        token: round(math.log((document_count + 1) / (frequency + 1)) + 1, 8)
        for token, frequency in document_frequency.items()
    }


def schema_vector(schema: dict[str, Any], schema_path: Path | None = None) -> dict[str, Any]:
    database = schema.get("database") or schema.get("db_id") or schema.get("mysql_database")
    tables = schema.get("tables", [])
    table_texts = [table_text(table) for table in tables]
    idf = build_idf(table_texts)
    return {
        "db_id": database,
        "source_schema": str(schema_path) if schema_path else None,
        "embedding_method": "tfidf_hash_v2",
        "dimension": DEFAULT_DIMENSION,
        "idf": idf,
        "tables": [
            {
                "name": table.get("name"),
                "text": text,
                "vector": embed_tokens(Counter(tokenize(text)), idf),
                "column_count": len(table.get("columns", [])),
                "has_fk": bool(table.get("foreign_keys")),
            }
            for table, text in zip(tables, table_texts)
        ],
    }


def schema_vector_path(schema_path: Path, output_dir: Path | None = None) -> Path:
    target_dir = output_dir or schema_path.parent.parent / "schema_vector"
    return target_dir / schema_path.name.replace("_schema.json", "_schema_vector.json")


def write_schema_vector_file(schema_path: Path, output_dir: Path | None = None) -> Path:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    output_path = schema_vector_path(schema_path, output_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema_vector(schema, schema_path), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def load_schema_vector(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rank_tables(question: str, vector_data: dict[str, Any]) -> list[dict[str, Any]]:
    dimension = int(vector_data.get("dimension", DEFAULT_DIMENSION))
    idf = vector_data.get("idf") or {}
    query_vector = embed_tokens(Counter(tokenize(question)), idf, dimension)
    ranked = []
    for table in vector_data.get("tables", []):
        score = cosine_similarity(query_vector, table.get("vector", []))
        ranked.append({"name": table.get("name"), "score": score})
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def filter_schema_tables(schema: dict[str, Any], table_names: list[str]) -> dict[str, Any]:
    selected = set(table_names)
    filtered = deepcopy(schema)
    filtered["tables"] = [
        table for table in schema.get("tables", []) if table.get("name") in selected
    ]
    filtered["selected_tables"] = table_names
    filtered["table_selection_method"] = "schema_vector_top_k"
    return filtered


def select_top_k_schema(schema: dict[str, Any], vector_data: dict[str, Any], question: str, top_k: int) -> dict[str, Any]:
    ranked = rank_tables(question, vector_data)
    selected_names = [item["name"] for item in ranked[:top_k] if item.get("name")]
    filtered = filter_schema_tables(schema, selected_names)
    filtered["selected_table_scores"] = ranked[:top_k]
    return filtered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate schema_vector JSON files.")
    parser.add_argument("--schema", type=Path, help="Path to one *_schema.json file.")
    parser.add_argument("--dataset", help="Dataset name under datasets/ (for all schemas).")
    parser.add_argument("--output-dir", type=Path, help="Output directory. Defaults to dataset/schema_vector.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if bool(args.schema) == bool(args.dataset):
        raise SystemExit("Pass exactly one of --schema or --dataset.")

    if args.schema:
        paths = [args.schema]
    else:
        paths = sorted((Path("datasets") / args.dataset / "schema_json").glob("*_schema.json"))

    if not paths:
        raise SystemExit("No schema JSON files found.")

    for schema_path in paths:
        output_path = write_schema_vector_file(schema_path, args.output_dir)
        print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
