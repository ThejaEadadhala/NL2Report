import json
from pathlib import Path
from engines.base_engine import BaseEngine


class DuckDBEngine(BaseEngine):

    def __init__(self, dataset: str | None = None, db_path: Path | str | None = None):
        """
        Pass `dataset` to auto-resolve the file from config/engine_config.json
        (with fallback to .sqlite if .duckdb doesn't exist yet).
        Pass `db_path` to use a specific file directly.
        """
        self._conn = None
        self.db_path = self._resolve_path(dataset, db_path)
        self._setup()

    @staticmethod
    def _load_config() -> dict:
        config_path = Path("config/engine_config.json")
        if config_path.exists():
            return json.loads(config_path.read_text())
        return {}

    def _resolve_path(self, dataset: str | None, db_path) -> Path:
        if dataset:
            config = self._load_config()
            ds_cfg = config.get(dataset, {})
            if isinstance(ds_cfg, dict):
                preferred = ds_cfg.get("file")
                fallback  = ds_cfg.get("fallback")
            else:
                preferred, fallback = None, None

            if preferred and Path(preferred).exists():
                return Path(preferred)
            if fallback and Path(fallback).exists():
                print(f"  [DuckDB] {preferred} not found — falling back to {fallback}")
                return Path(fallback)
            if db_path:
                return Path(db_path)
            raise FileNotFoundError(
                f"No database file found for dataset '{dataset}'. "
                f"Run the appropriate generate script first."
            )

        if db_path:
            return Path(db_path)
        raise ValueError("DuckDBEngine requires either dataset or db_path.")

    def _setup(self) -> None:
        import duckdb
        if self.db_path.suffix.lower() == ".sqlite":
            # Attach SQLite file and set it as the default catalog
            self._conn = duckdb.connect()
            self._conn.execute("INSTALL sqlite; LOAD sqlite;")
            escaped = str(self.db_path).replace("'", "''")
            self._conn.execute(f"ATTACH '{escaped}' AS db (TYPE sqlite)")
            self._conn.execute("USE db")
        else:
            # Native DuckDB file — connect directly, tables accessible by plain name
            self._conn = duckdb.connect(str(self.db_path))

    def execute_sql(self, sql: str) -> tuple[list, list, str | None]:
        try:
            sql = self.validate_read_only(sql)
            result = self._conn.execute(sql)
            rows = result.fetchall()
            columns = [desc[0] for desc in result.description] if result.description else []
            return columns, [list(r) for r in rows], None
        except Exception as e:
            return [], [], str(e)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
