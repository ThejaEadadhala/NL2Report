#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUMP_DIR="${1:-$ROOT_DIR/beaver_db}"

MYSQL_BIN="${MYSQL_BIN:-/usr/local/mysql/bin/mysql}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_HOST="${MYSQL_HOST:-localhost}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-Root@1234}"

# Check mysql binary
if [[ ! -x "$MYSQL_BIN" ]]; then
  echo "mysql binary not found at $MYSQL_BIN"
  echo "Set MYSQL_BIN or fix MySQL installation."
  exit 1
fi

# Validate dumps
for dump in "$DUMP_DIR"/dw.sql "$DUMP_DIR"/neutron.sql "$DUMP_DIR"/nova.sql; do
  if [[ ! -f "$dump" ]]; then
    echo "Missing dump file: $dump"
    exit 1
  fi
done

# Build auth args safely
AUTH_ARGS=(
  --host="$MYSQL_HOST"
  --port="$MYSQL_PORT"
  --user="$MYSQL_USER"
)

if [[ -n "$MYSQL_PASSWORD" ]]; then
  AUTH_ARGS+=(--password="$MYSQL_PASSWORD")
fi

# Import
for dump in "$DUMP_DIR"/dw.sql "$DUMP_DIR"/neutron.sql "$DUMP_DIR"/nova.sql; do
  echo "Importing $(basename "$dump")..."
  "$MYSQL_BIN" "${AUTH_ARGS[@]}" < "$dump"
done

echo "All imports completed successfully."