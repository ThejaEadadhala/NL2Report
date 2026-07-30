import requests
from models.base_model import BaseModel
from models.prompts import sql_system_prompt

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.1:8b"


class OllamaModel(BaseModel):
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def _generate(self, system: str, user: str) -> str:
        prompt = f"{system}\n\n{user}"
        response = requests.post(
            OLLAMA_URL,
            json={"model": self.model, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0}},
            timeout=300,
        )
        response.raise_for_status()
        return response.json()["response"].strip()

    def generate_sql(self, question: str, schema: dict) -> str:
        schema_text = self.format_schema(schema)
        engine = schema.get("engine", "sqlite")
        dialect = "MySQL" if engine == "mysql" else "DuckDB" if engine == "duckdb" else "SQLite"
        system = sql_system_prompt(dialect)
        db_name = schema.get("database") or schema.get("db_id", "")
        user = (
            f"{schema_text}\n\n"
            f"Question: {question}\n\n"
            f"IMPORTANT: Write plain table names only. NEVER prefix with the database name. "
            f"Wrong: FROM {db_name}.sales — Correct: FROM sales. "
            "SQL:"
        )
        self.log_prompt_token_lengths("SQLGenerator", system, user)
        raw = self._generate(system, user)
        return self._extract_sql(raw)
