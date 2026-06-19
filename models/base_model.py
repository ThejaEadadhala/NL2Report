from abc import ABC, abstractmethod


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
    def _quote(name: str) -> str:
        """Wrap column name in backticks if it contains spaces, parentheses, or %."""
        if any(ch in name for ch in (" ", "(", ")", "%")):
            return f"`{name}`"
        return name

    def format_schema(self, schema: dict) -> str:
        """Convert a schema dict (from extract_schema.py) into a compact text representation."""
        lines = [f"Database: {schema['database']}\n"]
        for table in schema["tables"]:
            cols = ", ".join(
                f"{self._quote(c['name'])} {c['type']}{'(PK)' if c['pk'] else ''}"
                + (f" [{c['description']}]" if c.get("description") else "")
                for c in table["columns"]
            )
            lines.append(f"Table {table['name']}: {cols}")
            if table["foreign_keys"]:
                fks = ", ".join(
                    f"{self._quote(fk['from'])} -> {fk['to_table']}.{self._quote(fk['to_col'])}"
                    for fk in table["foreign_keys"]
                )
                lines.append(f"  FK: {fks}")
        return "\n".join(lines)
