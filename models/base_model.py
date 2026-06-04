from abc import ABC, abstractmethod


class BaseModel(ABC):
    """Abstract interface every model adapter must implement."""

    @abstractmethod
    def generate_sql(self, question: str, schema: dict) -> str:
        """Given a natural language question and a schema dict, return a SQL query string."""
        ...

    def format_schema(self, schema: dict) -> str:
        """Convert a schema dict (from extract_schema.py) into a compact text representation."""
        lines = [f"Database: {schema['database']}\n"]
        for table in schema["tables"]:
            cols = ", ".join(
                f"{c['name']} {c['type']}{'(PK)' if c['pk'] else ''}"
                for c in table["columns"]
            )
            lines.append(f"Table {table['name']}: {cols}")
            if table["foreign_keys"]:
                fks = ", ".join(
                    f"{fk['from']} -> {fk['to_table']}.{fk['to_col']}"
                    for fk in table["foreign_keys"]
                )
                lines.append(f"  FK: {fks}")
        return "\n".join(lines)
