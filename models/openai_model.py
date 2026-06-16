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
        system = (
            "You are an expert SQLite assistant. "
            "Given a database schema and a natural language question, return ONLY a valid SQLite SQL query.\n\n"
            "STRICT RULES:\n"
            "1. Use ONLY the exact table names listed in the schema. Never use the database name as a table name.\n"
            "2. Use ONLY column names explicitly listed in the schema. Never invent column names.\n"
            "3. Wrap any column name containing spaces or special characters in backticks.\n"
            "4. NEVER prefix table names with the database name. Write FROM sales not FROM m5.sales, "
            "FROM orders not FROM tpch.orders.\n"
            "5. Alias syntax is always FROM tablename AS alias. NEVER write FROM alias alone. "
            "Correct: FROM sales AS T1. Wrong: FROM T1.\n"
            "6. Return ONLY the raw SQL query. No explanation, no markdown, no code fences."
        )
        user = f"{schema_text}\n\nQuestion: {question}\nSQL:"
        raw = self._generate(system, user)

        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines if not l.startswith("```")).strip()

        return raw
