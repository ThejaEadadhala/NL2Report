import os
from openai import OpenAI
from models.base_model import BaseModel

DEFAULT_MODEL = "gpt-4o"


class OpenAIModel(BaseModel):
    def __init__(self, model: str = DEFAULT_MODEL):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY not set. Add it to your .env file.")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate_sql(self, question: str, schema: dict) -> str:
        schema_text = self.format_schema(schema)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert SQLite assistant. "
                        "Given a database schema and a natural language question, "
                        "return ONLY a valid SQLite SQL query with no explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": f"{schema_text}\n\nQuestion: {question}\nSQL:",
                },
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()

        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines if not l.startswith("```")).strip()

        return raw
