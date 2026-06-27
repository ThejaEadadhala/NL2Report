import re
from abc import ABC, abstractmethod

_FORBIDDEN = re.compile(
    r"\b(ALTER|ATTACH|CREATE|DELETE|DETACH|DROP|INSERT|PRAGMA|REINDEX|REPLACE|UPDATE|VACUUM)\b",
    re.IGNORECASE,
)


class BaseEngine(ABC):

    @staticmethod
    def validate_read_only(sql: str) -> str:
        """Strip trailing semicolon and confirm the statement is a SELECT or WITH."""
        stripped = sql.strip().rstrip(";")
        first = stripped.split(None, 1)[0].upper() if stripped else ""
        if first not in {"SELECT", "WITH"}:
            raise ValueError("Only SELECT or WITH statements are allowed.")
        if ";" in stripped or _FORBIDDEN.search(stripped):
            raise ValueError("Only one read-only SQL statement is allowed.")
        return stripped

    @abstractmethod
    def execute_sql(self, sql: str) -> tuple[list, list, str | None]:
        """Execute SQL. Returns (columns, rows, error). error is None on success."""
        ...

    def close(self) -> None:
        pass
