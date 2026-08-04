import os
from openai import OpenAI as OpenAICompatibleClient
from models.base_model import BaseModel

DEFAULT_MODEL = "gpt-4o"
DEFAULT_API_MODEL = "gpt-4o"
DEFAULT_API_BASE_URL = "https://goapi.gptnb.ai/v1"


class OpenAIModel(BaseModel):
    def __init__(self, model: str | None = None, use_api: bool = False):
        self.use_api = use_api
        if use_api:
            api_key = os.getenv("GOAPI_API_KEY") or os.getenv("GPTNB_API_KEY")
            base_url = (
                os.getenv("GOAPI_BASE_URL")
                or os.getenv("GPTNB_BASE_URL")
                or DEFAULT_API_BASE_URL
            )
            self.model = model or os.getenv("GOAPI_MODEL") or os.getenv("GPTNB_MODEL") or DEFAULT_API_MODEL
            missing_key_message = "GOAPI_API_KEY or GPTNB_API_KEY not set. Add it to your .env file."
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            base_url = None
            self.model = model or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
            missing_key_message = "OPENAI_API_KEY not set. Add it to your .env file."

        if not api_key:
            raise EnvironmentError(missing_key_message)

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.chat_client = OpenAICompatibleClient(**client_kwargs)

    def _generate(self, system: str, user: str) -> str:
        response = self.chat_client.chat.completions.create(
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
        dialect = "MySQL version 9.7.x" if schema.get("engine") == "mysql" else "DuckDB" if schema.get("engine") == "duckdb" else "SQLite"
        system = (
            f"You are an expert {dialect} SQL generator. "
            f"Return exactly one valid {dialect} SELECT query for the user's question.\n\n"
            "Follow these rules:\n"
            "1. Use only tables and columns that appear in the provided schema. Never invent identifiers.\n"
            "2. Choose tables by matching the question's requested entities, measures, filters, and grain to the schema names and descriptions.\n"
            "3. Prefer the most direct table that already contains the requested measure or entity. Do not use a broader or similarly named table unless its columns match the question better.\n"
            "4. Join only on columns that are present in the schema and semantically represent the same key or entity. Do not create joins from name similarity alone.\n"
            "5. Preserve the requested result grain. If different measures require different grains, aggregate them in separate CTEs or subqueries, then join on the final entity grain.\n"
            "6. Use GROUP BY for grouped summaries. Use window functions only when the question asks for row-level values plus an analytic value such as rank, count-over, or average-over.\n"
            "7. Apply filters exactly as stated. Do not broaden filters, add unstated categories, or assume enum values that are not requested.\n"
            "8. Keep all requested output columns and ordering. Do not add extra columns unless needed to compute the result.\n"
            "9. Use syntax supported by the target dialect. Avoid dialect-specific functions unless they are valid for this dialect.\n"
            "10. Do not prefix table names with database names. Use aliases as: FROM table_name AS alias.\n"
            "11. Return only the SQL query: no markdown, comments, explanation, or code fences."
        )
        user = (
            "Schema:\n"
            f"{schema_text}\n\n"
            "Question:\n"
            f"{question}\n\n"
            "SQL:"
        )
        self.log_prompt_token_lengths("SQLGenerator", system, user)
        raw = self._generate(system, user)

        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines if not l.startswith("```")).strip()

        return raw

    def repair_sql(self, sql: str, errors: list[str], schema: dict | None = None) -> str:
        """Repair invalid SQL using the model and return only corrected SQL."""
        dialect = "MySQL version 9.7.0" if (schema or {}).get("engine") == "mysql" else "SQLite"
        error_text = "\n".join(errors) if errors else "Unknown SQL execution error."

        print(f"  [Repair] Starting SQL repair ({dialect}).")
        print(f"  [Repair] Original SQL length: {len(sql)} chars")

        system = (
            f"You are an expert {dialect} SQL repair assistant. "
            f"Given a failing SQL query, execution errors, and optionally the schema, rewrite it into valid {dialect} SQL. "
            "Preserve the user's intended result, use only schema-provided identifiers, and return only SQL."
        )
        user = (
            "Invalid SQL:\n"
            f"SQL:\n{sql}\n\n"
            f"Errors:\n{error_text}\n\n"
            "Schema:\n"
            f"{self.format_schema(schema) if schema else 'No schema provided.'}\n\n"
            f"Rewrite as one valid {dialect} SELECT query.\n"
            "Return only SQL."
        )

        print("  [Repair] Building repair prompt and counting tokens...")
        self.log_prompt_token_lengths("SQLRepair", system, user)
        print("  [Repair] Sending repair request to model...")
        repaired = self._generate(system, user)
        print(f"  [Repair] Received repaired SQL ({len(repaired)} chars)")

        if repaired.startswith("```"):
            lines = repaired.splitlines()
            repaired = "\n".join(l for l in lines if not l.startswith("```")).strip()
            print("  [Repair] Removed markdown fences from repaired SQL.")

        print("  [Repair] SQL repair completed.")
        return repaired
