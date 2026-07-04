import os
from openai import OpenAI
from models.base_model import BaseModel
from models.anthropic_model import _sql_system_prompt

DEFAULT_MODEL = "gpt-4o"


class OpenAIModel(BaseModel):
    def __init__(self, model: str = DEFAULT_MODEL):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY not set. Add it to your .env file.")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def _generate(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0,
        )
        return response.choices[0].message.content.strip()

    def generate_sql(self, question: str, schema: dict) -> str:
        schema_text = self.format_schema(schema)
        engine = schema.get("engine", "sqlite")
        dialect = "MySQL" if engine == "mysql" else "DuckDB" if engine == "duckdb" else "SQLite"
        system = _sql_system_prompt(dialect)
        user = f"{schema_text}\n\nQuestion: {question}\nSQL:"
        raw = self._generate(system, user)
        return self._extract_sql(raw)
