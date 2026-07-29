import os
import anthropic
from models.base_model import BaseModel
from models.prompts import sql_system_prompt

DEFAULT_API_MODEL = "anthropic-turbo"
DEFAULT_MODEL = DEFAULT_API_MODEL


class AnthropicModel(BaseModel):
    def __init__(self, model: str | None = None):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set. Add it to your .env file.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model or os.getenv("ANTHROPIC_MODEL") or DEFAULT_API_MODEL

    def _generate(self, system: str, user: str) -> str:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text.strip()

    def generate_sql(self, question: str, schema: dict) -> str:
        schema_text = self.format_schema(schema)
        engine = schema.get("engine", "sqlite")
        dialect = "MySQL" if engine == "mysql" else "DuckDB" if engine == "duckdb" else "SQLite"
        system = sql_system_prompt(dialect)
        user = f"{schema_text}\n\nQuestion: {question}\nSQL:"
        self.log_prompt_token_lengths("SQLGenerator", system, user)
        raw = self._generate(system, user)
        return self._extract_sql(raw)
