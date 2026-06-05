import requests
from models.base_model import BaseModel

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.1:8b"


class OllamaModel(BaseModel):
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def generate_sql(self, question: str, schema: dict) -> str:
        schema_text = self.format_schema(schema)
        prompt = (
            "You are an expert SQLite assistant.\n"
            "Given the database schema and a natural language question, return ONLY a valid SQLite SQL query.\n\n"
            "STRICT RULES — violating any rule produces invalid SQL:\n"
            "1. NEVER use the database name as a table name. Only use the exact table names listed in the schema.\n"
            "2. NEVER invent or guess column names. Only use column names that are explicitly listed in the schema.\n"
            "3. Every column name that contains spaces or special characters MUST be wrapped in backticks — e.g. `FRPM Count (K-12)`, `County Name`, `Enrollment (K-12)`.\n"
            "4. Before selecting any column, verify which table alias it belongs to. Never select a column from the wrong alias — e.g. if Phone is in the schools table aliased as T2, write T2.Phone not T1.Phone.\n"
            "5. NEVER prefix table names with the database name. Write FROM orders not FROM tpch.orders. Always define table aliases in the FROM clause before using them.\n"
            "6. Read the question carefully. Make sure your SELECT includes ALL columns the question asks for. Make sure GROUP BY matches exactly what the question wants to group by.\n"
            "7. Return ONLY the raw SQL query. No explanation, no markdown, no code fences.\n\n"
            f"{schema_text}\n\n"
            f"Question: {question}\n"
            "SQL:"
        )

        response = requests.post(
            OLLAMA_URL,
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        raw = response.json()["response"].strip()

        # Strip markdown code fences if the model adds them
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                l for l in lines if not l.startswith("```")
            ).strip()

        return raw
