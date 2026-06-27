import sqlite3
from pathlib import Path
from engines.base_engine import BaseEngine


class SQLiteEngine(BaseEngine):

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def execute_sql(self, sql: str) -> tuple[list, list, str | None]:
        try:
            sql = self.validate_read_only(sql)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            conn.close()
            return columns, [list(r) for r in rows], None
        except Exception as e:
            return [], [], str(e)
