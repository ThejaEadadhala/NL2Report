"""
single_grain_compiler.py
A lightweight SQL compiler layer focused on safer, single-grain analytical SQL.

Goals:
- detect grain mixing
- remove unsafe window usage
- stabilize CTE structure
- enforce simpler aggregation behavior
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WINDOW_RE = re.compile(r"\bOVER\s*\(", re.IGNORECASE)
_GROUP_BY_RE = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)
_WITH_RE = re.compile(r"^\s*WITH\b", re.IGNORECASE)

# MySQL often fails on DISTINCT inside window aggregates.
_DISTINCT_WINDOW_RE = re.compile(
    r"\b(COUNT|SUM|AVG)\s*\(\s*DISTINCT\s+([^\)]*?)\)\s*OVER\s*\(",
    re.IGNORECASE,
)

# Simplify OVER(PARTITION BY ... ORDER BY ...) to OVER(PARTITION BY ...) where possible.
_PARTITION_ORDER_RE = re.compile(
    r"OVER\s*\(\s*PARTITION\s+BY\s*([^\)]*?)\s+ORDER\s+BY\s*([^\)]*?)\)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class CompileReport:
    grain_mixing_detected: bool = False
    unsafe_window_removed: bool = False
    cte_stabilized: bool = False
    aggregation_simplified: bool = False
    actions: list[str] = field(default_factory=list)


def _find_top_level_order_by(sql: str) -> int:
    """Return index of first top-level ORDER BY in sql, or -1."""
    s = sql
    n = len(s)
    depth = 0
    i = 0
    in_single = False
    in_double = False

    while i < n:
        ch = s[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if in_single or in_double:
            i += 1
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)

        if depth == 0 and s[i : i + 8].upper() == "ORDER BY":
            return i

        i += 1

    return -1


def _stabilize_cte_structure(sql: str, report: CompileReport) -> str:
    """
    Remove top-level ORDER BY from CTE bodies unless they also include LIMIT/FETCH.
    This avoids unstable/non-portable ordering semantics inside intermediate CTEs.
    """
    if not _WITH_RE.search(sql):
        return sql

    out = sql
    idx = 0
    changed = False

    while True:
        as_idx = out.upper().find("AS (", idx)
        if as_idx == -1:
            break

        body_start = as_idx + 4  # points at '(' after AS 
        depth = 0
        end = -1
        i = body_start
        while i < len(out):
            if out[i] == "(":
                depth += 1
            elif out[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
            i += 1

        if end == -1:
            break

        body = out[body_start + 1 : end]
        order_idx = _find_top_level_order_by(body)
        if order_idx != -1:
            tail = body[order_idx:]
            if not re.search(r"\b(LIMIT|FETCH)\b", tail, re.IGNORECASE):
                body = body[:order_idx].rstrip()
                out = out[: body_start + 1] + body + out[end:]
                changed = True
                report.actions.append("Removed top-level ORDER BY inside CTE body")
                end = body_start + 1 + len(body)

        idx = end + 1

    if changed:
        report.cte_stabilized = True
    return out


def _remove_unsafe_window_usage(sql: str, report: CompileReport) -> str:
    out = sql

    def _distinct_repl(match: re.Match) -> str:
        report.unsafe_window_removed = True
        fn_name = match.group(1).upper()
        report.actions.append(f"Removed DISTINCT from windowed {fn_name} aggregate")
        return f"{match.group(1)}({match.group(2)}) OVER("

    out = _DISTINCT_WINDOW_RE.sub(_distinct_repl, out)
    return out


def _enforce_simpler_aggregation(sql: str, report: CompileReport) -> str:
    has_group_by = bool(_GROUP_BY_RE.search(sql))
    has_window = bool(_WINDOW_RE.search(sql))
    if not (has_group_by and has_window):
        return sql

    report.grain_mixing_detected = True
    report.actions.append("Detected potential grain mixing (GROUP BY + window functions)")

    def _partition_order_repl(match: re.Match) -> str:
        report.aggregation_simplified = True
        report.actions.append("Removed ORDER BY from PARTITION window to simplify aggregation")
        return f"OVER(PARTITION BY {match.group(1).strip()})"

    return _PARTITION_ORDER_RE.sub(_partition_order_repl, sql)


def compile_single_grain_sql(sql: str) -> tuple[str, CompileReport]:
    """Compile SQL into a safer single-grain form using conservative rewrites."""
    report = CompileReport()
    compiled = sql.strip()

    compiled = _stabilize_cte_structure(compiled, report)
    compiled = _remove_unsafe_window_usage(compiled, report)
    compiled = _enforce_simpler_aggregation(compiled, report)

    return compiled, report
