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
            "Given the database schema below and a natural language question, "
            "return ONLY a valid SQLite SQL query with no explanation.\n\n"
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
