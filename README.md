# NL2Report

NL-to-SQL pipeline for CP683 (Graduate Database Systems). Translates natural language questions into SQL, executes them against SQLite databases, and evaluates quality using Execution Accuracy (EX) and Valid SQL Rate.

## Architecture

```
pipeline/
  run_analysis.py       # Main entry point — single question interactive mode
  planning_agent.py     # Decomposes compound questions into sub-tasks
models/
  base_model.py         # Abstract interface + schema formatter
  ollama_model.py       # Llama 3.1 8B (local, via Ollama)
  anthropic_model.py    # Claude Sonnet 4.6
  openai_model.py       # GPT-4o
  gemini_model.py       # Gemini 2.0 Flash
evaluation/
  sql_evaluator.py      # Execution Accuracy + Valid SQL Rate
  run_eval.py           # Batch evaluation runner
scripts/
  extract_schema.py     # Extracts SQLite schema to JSON
  generate_tpch_sqlite.py   # Generates TPC-H SF=1 via DuckDB
  generate_tpch_schema.py   # Extracts TPC-H schema to JSON
  load_m5_sqlite.py     # Loads M5 CSVs into SQLite (wide→long unpivot)
  generate_m5_schema.py # Extracts M5 schema to JSON
datasets/
  bird/                 # BIRD benchmark (80 DBs, 1534 dev questions)
  tpch/                 # TPC-H SF=1 (~6M lineitem rows)
  m5/                   # M5 Forecasting (~58M sales rows)
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

### 2. Configure API keys

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIzaSy...
```

Keys are loaded automatically via `python-dotenv`. Only set the keys for models you intend to use.

### 3. Set up datasets

#### BIRD Benchmark
Download the BIRD dev/train splits from the official source and place them under:
```
datasets/bird/databases/dev/<db_name>/<db_name>.sqlite
datasets/bird/databases/train/<db_name>/<db_name>.sqlite
datasets/bird/dev.json
datasets/bird/train.json
```
Extract schemas for all databases:
```powershell
python scripts/extract_schema.py --dataset bird --split dev
python scripts/extract_schema.py --dataset bird --split train
```

#### TPC-H
Generate SF=1 SQLite database (~3-5 min, requires DuckDB):
```powershell
python scripts/generate_tpch_sqlite.py
python scripts/generate_tpch_schema.py
```

#### M5 Forecasting
Download `sales_train_validation.csv`, `sales_train_evaluation.csv`, and `calendar.csv` from Kaggle and place them in `datasets/m5/`. Then load into SQLite (~5-15 min):
```powershell
python scripts/load_m5_sqlite.py
python scripts/generate_m5_schema.py
```

> **Note:** The M5 `sales` table has ~58M rows. SQLite is slow for analytical workloads of this size. Indexes are added automatically during loading to speed up evaluation.

## Usage

### Single question (interactive mode)

```powershell
# BIRD
python pipeline/run_analysis.py --question "How many schools are in Alameda county?" --db california_schools --dataset bird --split dev --model anthropic

# TPC-H
python pipeline/run_analysis.py --question "What is the total revenue by nation?" --db tpch --dataset tpch --model anthropic

# M5
python pipeline/run_analysis.py --question "Which store had the highest total sales?" --db m5 --dataset m5 --model ollama
```

Available models: `ollama` | `anthropic` | `openai` | `gemini`

### Batch evaluation

```powershell
# Sample evaluation (10 questions per dataset)
venv\Scripts\python.exe evaluation\run_eval.py --dataset bird --questions sample_questions.json --model anthropic
venv\Scripts\python.exe evaluation\run_eval.py --dataset tpch --questions sample_questions.json --model anthropic
venv\Scripts\python.exe evaluation\run_eval.py --dataset m5   --questions sample_questions.json --model anthropic --limit 3

# Full BIRD dev evaluation (1534 questions — slow)
venv\Scripts\python.exe evaluation\run_eval.py --dataset bird --split dev --model ollama --limit 50

# Full TPC-H evaluation
venv\Scripts\python.exe evaluation\run_eval.py --dataset tpch --model ollama
```

Results are saved to `datasets/<dataset>/analysis_outputs/`:
- `eval_<model>_summary.json` — aggregated metrics
- `eval_<model>_detail.json` — per-question breakdown

## Evaluation Metrics

| Metric | Description |
|---|---|
| **Execution Accuracy (EX)** | % of questions where predicted SQL returns the exact same result set as gold SQL (row-order independent) |
| **Valid SQL Rate** | % of questions where predicted SQL executes without error |

EX is strict: column order differences, extra/missing aggregation columns, or semantically equivalent but structurally different queries all count as mismatches. Both metrics are reported together.

## Sample Results

Results on 10-question sample sets:

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

2. **Model hallucination**: llama3.1:8b invents column names not in the schema (e.g., `member.college`). Claude respects the schema precisely.

3. **Planning agent**: `PlanningAgent` uses the same LLM to decompose compound questions into sub-tasks. A programmatic guard collapses spurious splits — if the question contains no compound conjunction (`and`, `also`, `as well as`), it returns exactly one sub-task.

4. **M5 scalability**: SQLite is not suited for 58M-row analytical queries. Production NL2SQL systems should use OLAP engines (DuckDB, BigQuery, Snowflake). Indexes on the `sales` table (`d`, `store_id`, `cat_id`, `dept_id`) make evaluation tractable.

5. **Dataset difficulty ranking**: M5 > TPC-H > BIRD for model accuracy. M5 requires understanding the wide→long schema transformation; TPC-H requires multi-table joins with derived columns.

## Project Structure Notes

- `config.py` — path helpers and default model constant
- `datasets/<dataset>/schema_json/` — pre-extracted JSON schemas (one file per database)
- `datasets/<dataset>/sample_questions.json` — 10-question sample sets for quick evaluation
- `.env` — API keys (not committed to git)
