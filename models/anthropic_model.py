import os
import anthropic
from models.base_model import BaseModel

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicModel(BaseModel):
    def __init__(self, model: str = DEFAULT_MODEL):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set. Add it to your .env file.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def generate_sql(self, question: str, schema: dict) -> str:
        schema_text = self.format_schema(schema)
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=(
                "You are an expert SQLite assistant. "
                "Given a database schema and a natural language question, "
                "return ONLY a valid SQLite SQL query with no explanation."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"{schema_text}\n\nQuestion: {question}\nSQL:",
                }
            ],
        )
        raw = message.content[0].text.strip()

        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines if not l.startswith("```")).strip()

        return raw
