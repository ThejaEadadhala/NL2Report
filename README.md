# NL2Report

NL-to-SQL pipeline for CP683 (Graduate Database Systems). Translates natural language questions into SQL, executes them against SQLite or DuckDB or MySQL databases, and evaluates quality using Execution Accuracy (EX) and Valid SQL Rate.

## Architecture

```
pipeline/
  run_analysis.py       # Main entry point — single question interactive mode
  planning_agent.py     # Decomposes compound questions into sub-tasks
  batch_eval.py         # Resumable batch evaluation with per-question saves
  vector_filter.py      # Hash-based schema vector filter — trims large schemas to top-K tables

models/
  base_model.py         # Abstract interface + schema formatter (with column descriptions)
  ollama_model.py       # Llama 3.1 8B (local, via Ollama, temperature=0)
  anthropic_model.py    # Claude Sonnet 4.6
  openai_model.py       # GPT-4o
  gemini_model.py       # Gemini 2.0 Flash

engines/
  base_engine.py        # Abstract engine interface with read-only SQL validation
  sqlite_engine.py      # SQLite execution engine
  duckdb_engine.py      # DuckDB engine — native .duckdb or attached .sqlite fallback

evaluation/
  sql_evaluator.py      # Execution Accuracy + Valid SQL Rate
  run_eval.py           # Batch evaluation runner (legacy, per-dataset)

scripts/
  extract_schema.py           # Extracts SQLite schema to JSON
  extract_beaver_schema.py    # Extracts MySQL (Beaver) schema to JSON
  generate_tpch_sqlite.py     # Generates TPC-H SF=1 SQLite via DuckDB
  generate_tpch_duckdb.py     # Generates TPC-H SF=1 native DuckDB (faster)
  generate_tpch_schema.py     # Extracts TPC-H schema to JSON
  load_m5_sqlite.py           # Loads M5 CSVs into SQLite (wide→long)
  generate_m5_duckdb.py       # Loads M5 CSVs into native DuckDB (faster)
  generate_m5_schema.py       # Extracts M5 schema to JSON
  generate_schema_vectors.py  # Generates hash-based schema vectors for table retrieval
  import_beaver_mysql.sh      # Imports Beaver SQL dumps into MySQL

config/
  engine_config.json    # Per-dataset engine selection with file paths and fallbacks

datasets/
  bird/                 # BIRD benchmark (80 DBs, 1534 dev questions)
  tpch/                 # TPC-H SF=1 (~6M lineitem rows)
  m5/                   # M5 Forecasting (3 tables: calendar, sales ~58M rows, sales_evaluation ~59M rows)
  beaver/               # BEAVER enterprise benchmark (3 MySQL DBs: dw, neutron, nova)
```

## Setup

### 1. Install dependencies

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Ollama (for local inference): install from [ollama.com](https://ollama.com), then run:
```powershell
ollama pull llama3.1:8b
```
Note: Ollama processes one request at a time. The pipeline uses a 300s timeout per request to accommodate larger schemas (TPC-H, Beaver with vector filtering).

MySQL 8.0 (for Beaver dataset only): install MySQL Community Server, keep default port 3306.

### 2. Configure API keys

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIzaSy...

# OpenAI-compatible API mode for openai_model.py
GOAPI_API_KEY=sk-...
GOAPI_BASE_URL=https://goapi.gptnb.ai/v1
GOAPI_MODEL=gpt-4o

# OpenAI-compatible API mode for anthropic_model.py
ANTHROPIC_BASE_URL=https://goapi.gptnb.ai/v1
ANTHROPIC_MODEL=anthropic-turbo

# MySQL (Beaver dataset only)
MYSQL_USER=root
MYSQL_PASSWORD=yourpassword
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_BIN=C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe
```

Keys are loaded automatically via `python-dotenv`. Only set the keys for models you intend to use.

`openai_model.py` supports two modes:
- `--openai-mode library` uses `OPENAI_API_KEY` and the standard OpenAI endpoint.
- `--openai-mode api` uses the OpenAI-compatible API fields above (`GOAPI_API_KEY`, optional `GOAPI_BASE_URL`, optional `GOAPI_MODEL`).

`anthropic_model.py` supports two modes:
- `--anthropic-mode library` uses the Anthropic SDK.
- `--anthropic-mode api` uses an OpenAI-compatible API with `ANTHROPIC_MODEL=anthropic-turbo`.

### 3. Set up datasets

#### BIRD Benchmark (SQLite)
Download the BIRD dev/train splits from the official source and place them under:
```
datasets/bird/databases/dev/<db_name>/<db_name>.sqlite
datasets/bird/databases/train/<db_name>/<db_name>.sqlite
datasets/bird/dev.json
datasets/bird/train.json
```
Extract schemas:
```powershell
python scripts/extract_schema.py --dataset bird --split dev
python scripts/extract_schema.py --dataset bird --split train
```

#### TPC-H (DuckDB — recommended)
Generates SF=1 directly into a native DuckDB file (~17 seconds):
```powershell
python scripts/generate_tpch_duckdb.py
python scripts/generate_tpch_schema.py
```
Derived columns added: `l_net_revenue`, `l_ship_year`, `l_ship_month`, `o_year`, `o_month`, `o_quarter`, `c_has_debt`, `c_balance_tier`.

Alternatively, generate SQLite (3-5 min):
```powershell
python scripts/generate_tpch_sqlite.py
python scripts/generate_tpch_schema.py
```

#### M5 Forecasting (DuckDB — recommended)
Download `calendar.csv`, `sales_train_validation.csv`, and `sales_train_evaluation.csv` from Kaggle and place them in `datasets/m5/`. Then:
```powershell
python scripts/generate_m5_duckdb.py   # ~234s, 975 MB (3 tables: calendar, sales, sales_evaluation)
python scripts/generate_m5_schema.py
```
Alternatively, load into SQLite (~5-15 min):
```powershell
python scripts/load_m5_sqlite.py
python scripts/generate_m5_schema.py
```

#### BEAVER (MySQL)
Obtain the three SQL dump files (`dw.sql`, `neutron.sql`, `nova.sql`) and place them in `datasets/beaver/databases/`. Import into MySQL (requires MySQL 8.0 running on port 3306):
```bash
bash scripts/import_beaver_mysql.sh
```
Then extract schemas and generate schema vectors:
```powershell
python scripts/extract_beaver_schema.py
python scripts/generate_schema_vectors.py --dataset beaver
```
Schema JSON files and schema vectors are already committed to the repo — these steps are only needed to run live SQL against Beaver or regenerate the vectors.

### 4. Engine configuration

`config/engine_config.json` controls which execution engine each dataset uses:

```json
{
  "tpch": { "engine": "duckdb", "file": "datasets/tpch/tpch.duckdb", "fallback": "datasets/tpch/tpch.sqlite" },
  "m5":   { "engine": "duckdb", "file": "datasets/m5/m5.duckdb",    "fallback": "datasets/m5/m5.sqlite" },
  "bird": { "engine": "sqlite", "file": null, "fallback": null }
}
```

If the `.duckdb` file doesn't exist, the engine automatically falls back to `.sqlite` with a warning. Override per-run with `--engine sqlite|duckdb`.

## Usage

### Single question (interactive mode)

```powershell
# BIRD (SQLite)
python pipeline/run_analysis.py --question "How many schools are in Alameda county?" --db california_schools --dataset bird --split dev --model anthropic

# TPC-H (DuckDB by default)
python pipeline/run_analysis.py --question "What is the total revenue by order quarter?" --db tpch --dataset tpch --model anthropic

# M5 (DuckDB by default)
python pipeline/run_analysis.py --question "Which store had the highest total sales?" --db m5 --dataset m5 --model anthropic

# Force a specific engine
python pipeline/run_analysis.py --question "..." --db tpch --dataset tpch --model ollama --engine sqlite

# Beaver (MySQL, auto-detected from schema)
python pipeline/run_analysis.py --question "How many records are in the accounts table?" --db dw --dataset beaver --model anthropic
```

Available models: `ollama` | `anthropic` | `openai` | `gemini`

The output header shows which engine is active:
```
Question : What is the total revenue by order quarter?
Database : tpch (tpch/)
Model    : anthropic
Engine   : duckdb
```

### Batch evaluation (resumable)

`pipeline/batch_eval.py` runs the full pipeline on a questions file, saves after every question, and resumes automatically if interrupted:

```powershell
# TPC-H
python pipeline/batch_eval.py --dataset tpch --model ollama --questions datasets/tpch/tpch_questions.json

# BIRD
python pipeline/batch_eval.py --dataset bird --model anthropic --questions datasets/bird/sample_questions.json

# Beaver with openai_model.py through the OpenAI-compatible API
python3 pipeline/batch_eval.py --dataset beaver --model openai --openai-mode api --questions datasets/beaver/questions.json

# Beaver with anthropic_model.py through the OpenAI-compatible API
python3 pipeline/batch_eval.py --dataset beaver --model anthropic --anthropic-mode api --questions datasets/beaver/questions.json

# Custom output path
python pipeline/batch_eval.py --dataset tpch --model anthropic --questions datasets/tpch/tpch_questions.json --output results/tpch_anthropic.json
```

Output includes per-question `execution_time_seconds` and a final summary with near-miss count (same row count but different values).

### Evaluation UI

The Streamlit dashboard reads final judged artifacts from `results/*llm_judge*.json` or `results/*llm_judged*.json` and merges the matching raw execution file when it exists.

```powershell
streamlit run ui/app.py
```

The first version is an evaluation workbench: choose the judged result JSON, review experiment configuration, inspect generated SQL, compare gold and predicted row counts, and view query-level LLM judge outcomes plus aggregate metrics.

### Legacy batch evaluation

```powershell
# Sample evaluation (10 questions per dataset)
venv\Scripts\python.exe evaluation\run_eval.py --dataset bird --questions sample_questions.json --model anthropic
venv\Scripts\python.exe evaluation\run_eval.py --dataset tpch --questions sample_questions.json --model anthropic
venv\Scripts\python.exe evaluation\run_eval.py --dataset m5   --questions sample_questions.json --model anthropic --limit 3

# Full BIRD dev evaluation
venv\Scripts\python.exe evaluation\run_eval.py --dataset bird --split dev --model ollama --limit 50
```

Results are saved to `datasets/<dataset>/analysis_outputs/`:
- `eval_<model>_summary.json` — aggregated metrics
- `eval_<model>_detail.json` — per-question breakdown

## Evaluation Metrics

| Metric | Description |
|---|---|
| **Execution Accuracy (EX)** | % of questions where predicted SQL returns the exact same result set as gold SQL (row-order independent) |
| **Valid SQL Rate** | % of questions where predicted SQL executes without error |

EX is strict: column order differences, extra/missing aggregation columns, or semantically equivalent but structurally different queries all count as mismatches. Both metrics should be reported together.

## Sample Results

Results on 10-question sample sets (SQLite engine):

### BIRD (mixed dev + train databases)

| Model | EX | Valid SQL | Time |
|---|---|---|---|
| llama3.1:8b (Ollama) | 40% | 60% | 180.9s |
| Claude Sonnet 4.6 | 50% | 100% | 25.8s |

### TPC-H (SF=1)

| Model | EX | Valid SQL | Time |
|---|---|---|---|
| llama3.1:8b (5 Qs) | 40% | 100% | 108.2s |
| Claude Sonnet 4.6 (10 Qs) | 20% | 100% | 1734s |

### M5 Forecasting (3 questions, limited for time)

| Model | EX | Valid SQL | Time |
|---|---|---|---|
| Claude Sonnet 4.6 | 100% | 100% | 1173.6s |

## Key Findings

1. **Valid SQL vs EX gap**: Claude achieves 100% valid SQL but lower EX — queries are syntactically correct but return different column selections or orderings than the gold SQL. EX is a strict set-equality metric.

2. **Model hallucination**: llama3.1:8b invents column names not in the schema (e.g., `member.college`). Claude respects the schema precisely. Column descriptions in `format_schema()` help ground both models.

3. **Planning agent**: `PlanningAgent` uses the same LLM to decompose compound questions into sub-tasks. A programmatic guard collapses spurious splits — if the question contains no compound conjunction (`and`, `also`, `as well as`), it returns exactly one sub-task.

4. **SQLite vs DuckDB performance**: SQLite is slow for M5's 58M-row `sales` table. Switching to DuckDB as the execution engine dramatically reduces query time. TPC-H DuckDB generation takes 17s vs 3-5 min for SQLite.

5. **Multi-engine support**: The pipeline auto-detects the execution engine per dataset from `config/engine_config.json` — SQLite for BIRD, DuckDB for TPC-H and M5, MySQL for Beaver. Falls back gracefully to SQLite if the DuckDB file doesn't exist.

6. **Dataset difficulty ranking**: M5 > TPC-H > BIRD for model accuracy. M5 requires understanding the wide→long schema transformation; TPC-H requires multi-table joins with derived columns; Beaver databases have 97-175 tables requiring schema vector filtering.

7. **Schema vector retrieval**: Beaver databases have 97-175 tables — too large to pass the full schema to an LLM. Hash-based schema vectors in `datasets/beaver/schema_vector/` enable top-K (default 10) table selection per question. Wired into both `run_analysis.py` and `batch_eval.py` — no external ML dependencies, uses Blake2b hash embeddings at 384 dimensions.

## Project Structure Notes

- `config.py` — path helpers and default model constant
- `config/engine_config.json` — per-dataset engine and file path config
- `pipeline/vector_filter.py` — Blake2b hash-based schema vector filter; top-K table selection with no ML deps
- `datasets/<dataset>/schema_json/` — pre-extracted JSON schemas (one per database)
- `datasets/<dataset>/schema_vector/` — hash-based table embeddings for Beaver (384-dim, pre-computed)
- `datasets/<dataset>/sample_questions.json` — 10-question sample sets for quick evaluation
- `datasets/tpch/tpch_questions.json` — 10 TPC-H questions with gold SQL for `batch_eval.py`
- `.env` — API keys and MySQL credentials (not committed to git)
- Large data files (`.duckdb`, `.sqlite`, `.csv`, SQL dumps) are excluded from git via `.gitignore`
