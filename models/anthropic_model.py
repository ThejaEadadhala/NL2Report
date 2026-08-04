import os
from models.base_model import BaseModel
from models.prompts import sql_system_prompt

DEFAULT_API_MODEL = "claude-sonnet-4-6"
DEFAULT_MODEL = DEFAULT_API_MODEL
DEFAULT_API_BASE_URL = "https://goapi.gptnb.ai/v1"


class AnthropicModel(BaseModel):
    def __init__(self, model: str | None = None, use_api: bool = False):
        self.use_api = use_api
        if use_api:
            from openai import OpenAI as OpenAICompatibleClient

            api_key = (
                os.getenv("GOAPI_API_KEY")
            )
            base_url = (
                os.getenv("GOAPI_BASE_URL")
                or DEFAULT_API_BASE_URL
            )
            self.model = (
                model
                or os.getenv("ANTHROPIC_MODEL")
                or os.getenv("ANTHROPIC_API_MODEL")
                or DEFAULT_API_MODEL
            )
            missing_key_message = "ANTHROPIC_API_KEY, GOAPI_API_KEY not set. Add it to your .env file."
            if not api_key:
                raise EnvironmentError(missing_key_message)

            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            self.chat_client = OpenAICompatibleClient(**client_kwargs)
        else:
            api_key = os.getenv("ANTHROPIC_LIBRARY_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
            self.model = (
                model
                or os.getenv("ANTHROPIC_LIBRARY_MODEL")
                or os.getenv("ANTHROPIC_MODEL")
                or DEFAULT_MODEL
            )
            missing_key_message = "ANTHROPIC_LIBRARY_API_KEY or ANTHROPIC_API_KEY not set. Add it to your .env file."
            if not api_key:
                raise EnvironmentError(missing_key_message)
            import anthropic

            self.anthropic_client = anthropic.Anthropic(api_key=api_key)

    def _generate(self, system: str, user: str) -> str:
        if self.use_api:
            response = self.chat_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
            )
            return response.choices[0].message.content.strip()

        message = self.anthropic_client.messages.create(
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
