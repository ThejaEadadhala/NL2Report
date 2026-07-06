"""
run_eval.py
Runs all questions from a dataset through a model and reports scores.

Usage:
    # BIRD (has train/dev splits)
    python evaluation/run_eval.py --dataset bird --split dev --model ollama
    python evaluation/run_eval.py --dataset bird --split dev --model ollama --limit 50

    # TPC-H (no split — single SQLite file)
    python evaluation/run_eval.py --dataset tpch --model ollama
    python evaluation/run_eval.py --dataset tpch --model ollama --limit 10
"""

import argparse
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Always load the project-root .env regardless of current working directory.
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.sql_evaluator import evaluate_dataset
from pipeline.vector_filter import apply_vector_filter


def load_questions(dataset: str, split: str | None, questions_file: str | None = None) -> list[dict]:
    if questions_file:
        path = Path("datasets") / dataset / questions_file
    elif split:
        path = Path("datasets") / dataset / f"{split}.json"
    else:
        path = Path("datasets") / dataset / "questions.json"
    if not path.exists():
        raise FileNotFoundError(f"Questions file not found: {path}")
    return json.loads(path.read_text())


def load_schema(dataset: str, db_name: str) -> dict:
    path = Path("datasets") / dataset / "schema_json" / f"{db_name}_schema.json"
    return json.loads(path.read_text())


def make_db_finder(dataset: str, split: str | None):
    """Return a callable that resolves a db_name to its .sqlite path."""
    if split:
        # BIRD layout: databases/dev/california_schools/california_schools.sqlite
        db_base = Path("datasets") / dataset / "databases" / split
        def finder(db_name: str) -> Path:
            return db_base / db_name / f"{db_name}.sqlite"
    else:
        # Flat layout: search entire dataset folder (e.g. tpch/tpch.sqlite)
        dataset_root = Path("datasets") / dataset
        def finder(db_name: str) -> Path | None:
            matches = list(dataset_root.rglob(f"{db_name}.sqlite"))
            return matches[0] if matches else None
    return finder


def get_model(model_name: str, openai_mode: str = "library"):
    if model_name == "ollama":
        from models.ollama_model import OllamaModel
        return OllamaModel()
    elif model_name == "openai":
        from models.openai_model import OpenAIModel
        return OpenAIModel(use_api=openai_mode == "api")
    elif model_name == "anthropic":
        from models.anthropic_model import AnthropicModel
        return AnthropicModel()
    elif model_name == "gemini":
        from models.gemini_model import GeminiModel
        return GeminiModel()
    else:
        raise ValueError(f"Unknown model: {model_name}. Choose from: ollama, openai, anthropic, gemini")


def print_summary(results: dict, model_name: str, dataset: str, split: str | None, elapsed: float) -> None:
    s = results["summary"]
    errors = [r for r in results["results"] if r["pred_error"]]
    label = f"{dataset}/{split}" if split else dataset
    print("\n" + "=" * 50)
    print(f"  Evaluation Summary")
    print("=" * 50)
    print(f"  Model         : {model_name}")
    print(f"  Dataset       : {label}")
    print(f"  Total Qs      : {s['total']}")
    print(f"  Execution Acc : {s['execution_accuracy']:.2%}")
    print(f"  Valid SQL Rate: {s['valid_sql_rate']:.2%}")
    print(f"  Errors        : {len(errors)}")
    print(f"  Time          : {elapsed:.1f}s")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="NL2Report evaluation runner")
    parser.add_argument("--dataset", default="bird", help="Dataset: bird | tpch (default: bird)")
    parser.add_argument("--split", default=None, help="Split: dev | train — omit for datasets with no split (e.g. tpch)")
    parser.add_argument("--model", default="ollama", help="Model: ollama | openai | anthropic (default: ollama)")
    parser.add_argument("--openai-mode", default="library", choices=["library", "api"],
                        help="OpenAI adapter mode: library uses OPENAI_API_KEY; api uses OpenAI-compatible API env vars")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of questions for quick tests")
    parser.add_argument("--questions", default=None, help="Custom questions filename (e.g. sample_questions.json)")
    args = parser.parse_args()

    # Default split for BIRD — but not when using a custom questions file
    # (custom file may reference databases from both dev and train)
    if args.dataset == "bird" and args.split is None and args.questions is None:
        args.split = "dev"

    label = args.questions or (f"{args.split}.json" if args.split else "questions.json")
    print(f"\nLoading {label}...")
    questions = load_questions(args.dataset, args.split, args.questions)
    print(f"Loaded {len(questions)} questions")

    if args.limit:
        print(f"Limiting to first {args.limit} questions")

    db_finder     = make_db_finder(args.dataset, args.split)
    model         = get_model(args.model, args.openai_mode)
    schema_loader = lambda db_name: load_schema(args.dataset, db_name)
    schema_filter = lambda schema, db_name, q, gold_sql=None: apply_vector_filter(
        schema,
        args.dataset,
        db_name,
        q,
        gold_sql=gold_sql,
    )

    print(f"\nRunning evaluation with [{args.model}]...\n")
    if args.model == "openai":
        print(f"OpenAI mode: {args.openai_mode}\n")
    start = time.time()

    results = evaluate_dataset(
        questions=questions,
        db_finder=db_finder,
        model=model,
        schema_loader=schema_loader,
        max_questions=args.limit,
        schema_filter=schema_filter,
    )

    elapsed = time.time() - start
    print_summary(results, args.model, args.dataset, args.split, elapsed)

    out_dir = Path("datasets") / args.dataset / "analysis_outputs"
    out_dir.mkdir(exist_ok=True)

    tag = f"{args.model}_{args.split}" if args.split else args.model
    summary_file = out_dir / f"eval_{tag}_summary.json"
    detail_file  = out_dir / f"eval_{tag}_detail.json"

    summary_file.write_text(json.dumps(results["summary"], indent=2))
    detail_file.write_text(json.dumps(results["results"], indent=2))

    print(f"\n  Summary saved to {summary_file}")
    print(f"  Details saved to {detail_file}")


if __name__ == "__main__":
    main()
