import os
import anthropic
from models.base_model import BaseModel

DEFAULT_MODEL = "claude-sonnet-4-6"


def _sql_system_prompt(dialect: str) -> str:
    return (
        f"You are an expert {dialect} SQL assistant. "
        f"Given a database schema and a natural language question, return ONLY a valid {dialect} SQL query.\n\n"
        "STRICT RULES — follow every rule exactly:\n"
        "1. Use ONLY the exact table and column names listed in the schema. Never invent names.\n"
        "2. NEVER prefix table names with the database name. Write FROM sales not FROM m5.sales.\n"
        "3. Alias syntax: FROM tablename AS alias. NEVER write FROM alias alone.\n"
        "4. Wrap column names containing spaces or special characters in backticks.\n"
        "5. Before writing a JOIN, verify the join key exists in BOTH tables in the schema.\n"
        "6. Before adding a JOIN, check if all needed columns already exist in one table — if so, no JOIN is needed.\n"
        "7. Use WHERE for row-level filters and HAVING for aggregate filters.\n"
        "8. For multi-step analytical queries, use CTEs (WITH clauses) rather than deeply nested subqueries.\n"
        "9. Window functions: use OVER (PARTITION BY ... ORDER BY ... ROWS BETWEEN ...) syntax exactly.\n"
        "10. For standard deviation and variance: "
        "in MySQL and DuckDB use STDDEV() and VARIANCE(); "
        "in SQLite these functions do not exist — compute manually: "
        "SQRT(AVG(x*x) - AVG(x)*AVG(x)) for stddev, AVG(x*x) - AVG(x)*AVG(x) for variance. "
        "Never use STDDEV_POP() or VAR_POP(). Never round unless asked.\n"
        "11. If the schema does not contain a column or table needed to answer the question, "
        "use NULL AS column_name as a placeholder — do NOT output explanations or reasoning.\n"
        "12. Return ONLY the raw SQL query. No explanation, no markdown, no code fences, no prose."
    )


class AnthropicModel(BaseModel):
    def __init__(self, model: str = DEFAULT_MODEL):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set. Add it to your .env file.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

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
        system = _sql_system_prompt(dialect)
        user = f"{schema_text}\n\nQuestion: {question}\nSQL:"
        self.log_prompt_token_lengths("SQLGenerator", system, user)
        raw = self._generate(system, user)
        return self._extract_sql(raw)
