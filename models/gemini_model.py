import os
from google import genai
from google.genai import types
from models.base_model import BaseModel
from models.anthropic_model import _sql_system_prompt

DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiModel(BaseModel):
    def __init__(self, model: str = DEFAULT_MODEL):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY not set. Add it to your .env file.")
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def _generate(self, system: str, user: str) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
            ),
        )
        return response.text.strip()

    def generate_sql(self, question: str, schema: dict) -> str:
        schema_text = self.format_schema(schema)
        engine = schema.get("engine", "sqlite")
        dialect = "MySQL" if engine == "mysql" else "DuckDB" if engine == "duckdb" else "SQLite"
        system = _sql_system_prompt(dialect)
        user = f"{schema_text}\n\nQuestion: {question}\nSQL:"
        self.log_prompt_token_lengths("SQLGenerator", system, user)
        raw = self._generate(system, user)
        return self._extract_sql(raw)
