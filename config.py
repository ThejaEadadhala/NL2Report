from pathlib import Path

# Project root (one level up from this file)
ROOT = Path(__file__).parent

# Dataset paths
DATASETS_DIR = ROOT / "datasets"

def db_path(dataset: str, split: str, db_name: str) -> Path:
    return DATASETS_DIR / dataset / "databases" / split / db_name / f"{db_name}.sqlite"

def schema_path(dataset: str, db_name: str) -> Path:
    return DATASETS_DIR / dataset / "schema_json" / f"{db_name}_schema.json"

def questions_path(dataset: str, split: str) -> Path:
    return DATASETS_DIR / dataset / f"{split}.json"

def analysis_output_path(dataset: str) -> Path:
    return DATASETS_DIR / dataset / "analysis_outputs"

# Available models
MODELS = ["ollama", "openai", "anthropic"]
DEFAULT_MODEL = "ollama"
