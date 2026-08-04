# NL2Report

NL2Report is a multi-agent NL-to-SQL evaluation workbench. It converts natural language analytical questions into SQL, retrieves the relevant schema context, executes the query on the correct database engine, compares the result with gold SQL when available, and displays the outputs in a Streamlit UI.

The current supported model backends are:

- `openai` — GPT-4o, usually run with `--openai-mode api`
- `anthropic` — Claude-compatible model through API mode, usually run with `--anthropic-mode api`
- `ollama` — local model, default `llama3.1:8b`

## Project Layout

```text
pipeline/
  run_analysis.py          # Single-question pipeline
  batch_eval.py            # Resumable batch evaluation and automatic LLM judging
  planning_agent.py        # Conservative analytical sub-task planning
  vector_filter.py         # Hash-based schema retrieval for large schemas
  single_grain_compiler.py # Lightweight SQL compiler/validator layer

models/
  base_model.py            # Shared model interface and schema formatter
  openai_model.py          # OpenAI / OpenAI-compatible API backend
  anthropic_model.py       # Anthropic SDK or OpenAI-compatible API backend
  ollama_model.py          # Local Ollama backend

engines/
  sqlite_engine.py         # SQLite execution
  duckdb_engine.py         # DuckDB execution

scripts/
  extract_schema.py
  extract_beaver_schema.py
  generate_schema_vectors.py
  generate_tpch_duckdb.py
  generate_tpch_schema.py
  generate_m5_duckdb.py
  generate_m5_schema.py
  import_beaver_mysql.sh

ui/
  app.py                   # Streamlit evaluation UI

config/
  engine_config.json       # Dataset-to-engine configuration
```

## Setup

Create and activate a Python environment, then install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

For Ollama:

```bash
ollama pull llama3.1:8b
```

For BEAVER, install MySQL 8.0 and keep it running on the configured host and port.

## Environment

Create a `.env` file in the project root. Use only the keys you need.

```env
# OpenAI standard library mode
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# OpenAI-compatible API mode for OpenAI runs
GOAPI_API_KEY=sk-...
GOAPI_BASE_URL=https://goapi.gptnb.ai/v1
GOAPI_MODEL=gpt-4o

# Anthropic standard library mode
ANTHROPIC_LIBRARY_API_KEY=sk-ant-...
ANTHROPIC_LIBRARY_MODEL=claude-sonnet-4-6

# Anthropic API mode through an OpenAI-compatible endpoint
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_BASE_URL=https://goapi.gptnb.ai/v1
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_API_MODEL=claude-sonnet-4-6

# Optional shared OpenAI-compatible aliases
GPTNB_API_KEY=sk-...
GPTNB_BASE_URL=https://goapi.gptnb.ai/v1
GPTNB_MODEL=gpt-4o

# BEAVER MySQL
MYSQL_USER=root
MYSQL_PASSWORD=yourpassword
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
```

Mode behavior:

- `--openai-mode api` uses `GOAPI_API_KEY` or `GPTNB_API_KEY`, plus `GOAPI_MODEL` / `GPTNB_MODEL`.
- `--openai-mode library` uses `OPENAI_API_KEY`.
- `--anthropic-mode api` uses `ANTHROPIC_API_KEY`, `GOAPI_API_KEY`, or `GPTNB_API_KEY` with an OpenAI-compatible endpoint.
- `--anthropic-mode library` uses the Anthropic SDK with `ANTHROPIC_LIBRARY_API_KEY` or `ANTHROPIC_API_KEY`.

## Datasets

The project uses four datasets:

- `beaver` — MySQL enterprise schemas: `dw`, `nova`, `neutron`
- `bird` — SQLite benchmark databases
- `tpch` — DuckDB analytical benchmark
- `m5` — DuckDB retail/forecasting dataset

### BEAVER

Place BEAVER SQL dumps in:

```text
datasets/beaver/databases/
```

Import them:

```bash
bash scripts/import_beaver_mysql.sh
```

Regenerate schemas and schema vectors when needed:

```bash
python3 scripts/extract_beaver_schema.py
python3 scripts/generate_schema_vectors.py --dataset beaver
```

### BIRD

Place BIRD databases and metadata under:

```text
datasets/bird/databases/dev/<db_name>/<db_name>.sqlite
datasets/bird/databases/train/<db_name>/<db_name>.sqlite
datasets/bird/dev.json
datasets/bird/train.json
```

Extract schemas:

```bash
python3 scripts/extract_schema.py --dataset bird --split dev
python3 scripts/extract_schema.py --dataset bird --split train
```

### TPC-H

Generate DuckDB data and schema:

```bash
python3 scripts/generate_tpch_duckdb.py
python3 scripts/generate_tpch_schema.py
```

### M5

Place the M5 CSV files in `datasets/m5/`, then generate DuckDB data and schema:

```bash
python3 scripts/generate_m5_duckdb.py
python3 scripts/generate_m5_schema.py
```

## Engine Configuration

Execution engines are selected from `config/engine_config.json`.

Current behavior:

- BEAVER uses MySQL from its schema metadata.
- BIRD uses SQLite.
- TPC-H uses DuckDB.
- M5 uses DuckDB.

The UI and batch evaluator both use this configuration.

## Running A Single Question

OpenAI API mode:

```bash
python3 pipeline/run_analysis.py \
  --question "What is the total revenue by order quarter?" \
  --dataset tpch \
  --db tpch \
  --model openai \
  --openai-mode api
```

Anthropic API mode:

```bash
python3 pipeline/run_analysis.py \
  --question "For each network, show its number of ports." \
  --dataset beaver \
  --db neutron \
  --model anthropic \
  --anthropic-mode api
```

Ollama local mode:

```bash
python3 pipeline/run_analysis.py \
  --question "How many schools are in Alameda county?" \
  --dataset bird \
  --db california_schools \
  --split dev \
  --model ollama
```

## Running Batch Evaluation

`pipeline/batch_eval.py` saves after every question and resumes automatically if interrupted. It also runs the LLM judge unless `--skip-judge` is passed.

OpenAI API mode:

```bash
python3 pipeline/batch_eval.py \
  --dataset beaver \
  --model openai \
  --openai-mode api \
  --questions datasets/beaver/dw_questions.json
```

Anthropic API mode:

```bash
python3 pipeline/batch_eval.py \
  --dataset beaver \
  --model anthropic \
  --anthropic-mode api \
  --questions datasets/beaver/neutron_questions.json
```

Ollama local mode:

```bash
python3 pipeline/batch_eval.py \
  --dataset tpch \
  --model ollama \
  --questions datasets/tpch/tpch_questions.json
```

Custom output path:

```bash
python3 pipeline/batch_eval.py \
  --dataset m5 \
  --model openai \
  --openai-mode api \
  --questions datasets/m5/questions.json \
  --output results/m5_openai_results.json
```

The judge follows the selected model by default. For example, `--model anthropic --anthropic-mode api` uses Anthropic API mode for both SQL generation and judging.

## Running The UI

```bash
streamlit run ui/app.py
```

The UI supports:

- model selection between OpenAI and Anthropic
- dataset and database selection
- manual question input
- loading one sample question or all questions from a dataset question JSON file
- pipeline progress display
- analytical plan tab
- retrieved schema tab
- generated SQL tab
- execution result tab
- analytical report tab
- evaluation cards and metrics dashboard

Judged results are loaded from files in `results/` matching `*llm_judge*.json`, `*llm_judged*.json`, `*judge*.json`, or `*judged*.json`.

## Evaluation Artifacts

Batch and UI runs write JSON files under `results/`. Raw execution files contain fields such as:

- question
- gold SQL
- predicted SQL
- repaired SQL, when available
- repair status
- compiler actions
- validity
- exact result match
- gold and predicted row counts
- execution time
- execution error, when present

Judge files add:

- judge model
- judge mode
- judge score
- judge verdict
- judge reason
- aggregate summary metrics

## Schema Vector Retrieval

BEAVER databases are large: `dw`, `nova`, and `neutron` contain many tables. Passing the full schema to the LLM can exceed useful context and add irrelevant noise.

NL2Report uses hash-based schema vectors for BEAVER:

1. Table text is built from table names, column names, descriptions, keys, and metadata.
2. Each table is converted into a fixed-size hash-based vector.
3. The user question is converted into the same vector space.
4. Cosine similarity selects the top relevant tables.
5. Only the selected schema is passed to the model.

This is lightweight, local, and does not require an external embedding service. Future work can make retrieval more generic with column-level retrieval, schema graph traversal, join-path reasoning, and learned embeddings.

## Metrics

The project reports:

- exact result match against gold SQL when available
- valid SQL rate
- execution errors
- row-count comparison
- LLM judge verdicts: correct, partially correct, incorrect, parse error, or judge error
- average judge score and correctness percentage

Exact result match is intentionally strict. The LLM judge is used as an additional semantic evaluator when exact comparison is too brittle.
