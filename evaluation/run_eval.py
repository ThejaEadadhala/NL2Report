"""
run_eval.py
Runs all questions from a dataset split through a model and reports scores.

Usage:
    python evaluation/run_eval.py --dataset bird --split dev --model ollama
    python evaluation/run_eval.py --dataset bird --split dev --model openai --limit 50
    python evaluation/run_eval.py --dataset bird --split dev --model anthropic --limit 100
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.sql_evaluator import evaluate_dataset


def load_questions(dataset: str, split: str) -> list[dict]:
    path = Path("datasets") / dataset / f"{split}.json"
    if not path.exists():
        raise FileNotFoundError(f"Questions file not found: {path}")
    return json.loads(path.read_text())


def load_schema(dataset: str, db_name: str) -> dict:
    path = Path("datasets") / dataset / "schema_json" / f"{db_name}_schema.json"
    return json.loads(path.read_text())


def get_model(model_name: str):
    if model_name == "ollama":
        from models.ollama_model import OllamaModel
        return OllamaModel()
    elif model_name == "openai":
        from models.openai_model import OpenAIModel
        return OpenAIModel()
    elif model_name == "anthropic":
        from models.anthropic_model import AnthropicModel
        return AnthropicModel()
    else:
        raise ValueError(f"Unknown model: {model_name}. Choose from: ollama, openai, anthropic")


def print_summary(results: dict, model_name: str, split: str, elapsed: float) -> None:
    print("\n" + "=" * 50)
    print(f"  Evaluation Summary")
    print("=" * 50)
    print(f"  Model         : {model_name}")
    print(f"  Split         : {split}")
    print(f"  Total Qs      : {results['total']}")
    print(f"  Execution Acc : {results['execution_accuracy']:.2%}")
    print(f"  Valid SQL Rate: {results['valid_sql_rate']:.2%}")
    print(f"  Errors        : {len(results['errors'])}")
    print(f"  Time          : {elapsed:.1f}s")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="NL2Report evaluation runner")
    parser.add_argument("--dataset", default="bird", help="Dataset name (default: bird)")
    parser.add_argument("--split", default="dev", help="Split: dev | train (default: dev)")
    parser.add_argument("--model", default="ollama", help="Model: ollama | openai | anthropic (default: ollama)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of questions (useful for quick tests)")
    args = parser.parse_args()

    print(f"\nLoading {args.split}.json...")
    questions = load_questions(args.dataset, args.split)
    print(f"Loaded {len(questions)} questions")

    if args.limit:
        print(f"Limiting to first {args.limit} questions")

    db_base = Path("datasets") / args.dataset / "databases" / args.split
    model = get_model(args.model)
    schema_loader = lambda db_name: load_schema(args.dataset, db_name)

    print(f"\nRunning evaluation with [{args.model}]...\n")
    start = time.time()

    results = evaluate_dataset(
        questions=questions,
        db_base=db_base,
        model=model,
        schema_loader=schema_loader,
        max_questions=args.limit,
    )

    elapsed = time.time() - start
    print_summary(results, args.model, args.split, elapsed)

    # Save results to analysis_outputs
    out_dir = Path("datasets") / args.dataset / "analysis_outputs"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"eval_{args.model}_{args.split}.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"\n  Results saved to {out_file}")


if __name__ == "__main__":
    main()
