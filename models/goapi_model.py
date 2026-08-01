import os
from openai import OpenAI
from models.base_model import BaseModel

GOAPI_BASE_URL = "https://goapi.gptnb.ai/v1"
DEFAULT_MODEL  = "claude-sonnet-4-6"

class GoAPIModel(BaseModel):
    def __init__(self, model: str = DEFAULT_MODEL):
        api_key = os.getenv("GOAPI_API_KEY") or os.getenv("GOAPI_KEY")
        if not api_key:
            raise EnvironmentError("GOAPI_API_KEY not set in .env")
        self.client = OpenAI(api_key=api_key, base_url=GOAPI_BASE_URL)
        self.model = model

    def _generate(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.0,
            max_tokens=1024,
        )
        return response.choices[0].message.content.strip()

    def generate_sql(self, question: str, schema: dict) -> str:
        schema_text = self.format_schema(schema)
        system = (
            "You are an expert DuckDB SQL assistant. "
            "Given a database schema and a natural language question, return ONLY a valid SQL query.\n\n"
            "STRICT RULES:\n"
            "1. Use ONLY the exact table names listed in the schema.\n"
            "2. Use ONLY column names explicitly listed in the schema.\n"
            "3. NEVER prefix table names with the database name.\n"
            "4. Alias syntax: FROM tablename AS alias.\n"
            "5. Return ONLY the raw SQL. No explanation, no markdown, no code fences."
        )
        user = f"{schema_text}\n\nQuestion: {question}\nSQL:"
        self.log_prompt_token_lengths("SQLGenerator", system, user)
        raw = self._generate(system, user)
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines if not l.startswith("```")).strip()
        return raw
