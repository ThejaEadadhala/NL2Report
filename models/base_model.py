import re
from abc import ABC, abstractmethod

_SQL_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
# SQL WITH must be followed by an identifier then AS ( — distinguishes from English "With the..."
_SQL_CTE_RE  = re.compile(r"\bWITH\s+\w+\s+AS\s*\(", re.IGNORECASE)
_SQL_SELECT_RE = re.compile(r"\bSELECT\b", re.IGNORECASE)


class BaseModel(ABC):
    """Abstract interface every model adapter must implement."""

    @abstractmethod
    def generate_sql(self, question: str, schema: dict) -> str:
        """Given a natural language question and a schema dict, return a SQL query string."""
        ...

    def _generate(self, system: str, user: str) -> str:
        """Raw LLM call with a system prompt and user message. Implemented by each adapter."""
        raise NotImplementedError(f"{type(self).__name__} does not implement _generate")

    @staticmethod
    def _extract_sql(raw: str) -> str:
        """
        Extract the first valid SQL block from a model response.
        Handles: fenced code blocks, inline reasoning before SELECT/WITH,
        and bare SQL with no wrapper.
        """
        # 1. Prefer content inside ```sql ... ``` or ``` ... ``` fences
        fence_match = _SQL_FENCE_RE.search(raw)
        if fence_match:
            return fence_match.group(1).strip()

        # 2. Look for CTE pattern: WITH <identifier> AS ( — unambiguously SQL
        cte_match = _SQL_CTE_RE.search(raw)
        if cte_match:
            return raw[cte_match.start():].strip()

        # 3. Fall back to first SELECT keyword
        select_match = _SQL_SELECT_RE.search(raw)
        if select_match:
            return raw[select_match.start():].strip()

        # 4. Return as-is and let the validator catch it
        return raw.strip()

    @staticmethod
    def _quote(name: str) -> str:
        """Wrap identifiers in backticks when they need quoting."""
        if any(ch in name for ch in (" ", "(", ")", "%", "-")):
            return f"`{name}`"
        return name

    def format_schema(self, schema: dict) -> str:
        """Convert a schema dict (from extract_schema.py) into a compact text representation."""
        database = schema.get("database") or schema.get("db_id") or schema.get("mysql_database")
        engine = schema.get("engine", "sqlite")
        dialect = "MySQL" if engine == "mysql" else "DuckDB" if engine == "duckdb" else "SQLite"
        lines = [f"Database: {database}", f"Dialect: {dialect}\n"]
        for table in schema["tables"]:
            cols = ", ".join(
                f"{self._quote(c['name'])} {c.get('type', '')}"
                + ("(PK)" if c.get("pk") or c.get("primary_key_position") else "")
                + (
                    f" [{c.get('description') or c.get('beaver_description', {}).get('description')}]"
                    if c.get("description") or c.get("beaver_description", {}).get("description")
                    else ""
                )
                for c in table["columns"]
            )
            lines.append(f"Table {table['name']}: {cols}")
            if table["foreign_keys"]:
                fks = ", ".join(
                    f"{self._quote(fk.get('from') or fk.get('from_column'))} -> "
                    f"{fk['to_table']}.{self._quote(fk.get('to_col') or fk.get('to_column'))}"
                    for fk in table["foreign_keys"]
                )
                lines.append(f"  FK: {fks}")
        return "\n".join(lines)
