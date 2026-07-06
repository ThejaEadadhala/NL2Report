"""
planning_agent.py
=================
Decomposes a high-level analytical question into an ordered list of
sub-questions, each answerable by a single SQL query.

For simple questions it returns [question] unchanged — no forced decomposition.

Usage (called internally by run_analysis.py):
    from pipeline.planning_agent import PlanningAgent

    agent = PlanningAgent(model)          # any BaseModel instance
    subtasks = agent.plan(question, schema)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.base_model import BaseModel

_SYSTEM_PROMPT = (
    "You are a query planning agent.\n"
    "Given a database schema and a user's analytical question, output a JSON array of sub-questions.\n\n"
    "CRITICAL RULE: Return EXACTLY ONE element unless the question explicitly contains the words "
    "'and', 'also', or 'as well as' joining two clearly separate analytical goals.\n"
    "When in doubt, return ONE element. Never invent sub-questions not asked for.\n\n"
    "AGGREGATION RULE: If all metrics in the question are grouped by the SAME dimension "
    "(e.g., all 'per department', all 'per region', all 'per category'), always return ONE element — "
    "even if the question uses 'and' or 'also'. These can be combined into one SQL query with a CTE.\n\n"
    "ONE element — these are single goals:\n"
    "  [\"What is the total revenue by region?\"]\n"
    "  [\"How many records exist per category?\"]\n"
    "  [\"For each department, show the average supervisees, total sqft, and total research volume.\"]\n"
    "TWO elements — only when the two goals have DIFFERENT grouping dimensions or require separate queries:\n"
    "  [\"What are total sales by region?\", \"Which individual customer had the highest single purchase?\"]\n\n"
    "Respond with ONLY a JSON array of strings. No explanation, no markdown, no code fences."
)


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        lines = raw.splitlines()
        return "\n".join(l for l in lines if not l.startswith("```")).strip()
    return raw


def _parse(raw: str, fallback: str) -> list[str]:
    """Parse JSON array from LLM response. Falls back to [fallback] on any failure."""
    try:
        result = json.loads(_strip_fences(raw))
        if isinstance(result, list) and result:
            return [str(s).strip() for s in result]
    except (json.JSONDecodeError, ValueError):
        pass
    return [fallback]


class PlanningAgent:
    """
    Wraps any BaseModel instance to provide query planning.
    All planning prompt logic lives here — the model adapter only provides _generate().
    """

    def __init__(self, model: BaseModel):
        self._model = model

    def plan(self, question: str, schema: dict) -> list[str]:
        """
        Return an ordered list of sub-questions for the given question + schema.
        Always returns at least [question] — never raises, never returns empty.
        """
        schema_text = self._model.format_schema(schema)
        user = f"{schema_text}\n\nQuestion: {question}\nPlan (JSON array):"

        try:
            self._model.log_prompt_token_lengths("PlanningAgent", _SYSTEM_PROMPT, user)
            raw = self._model._generate(_SYSTEM_PROMPT, user)
            result = _parse(raw, question)
            # Never allow more than 2 subtasks — anything beyond that
            # indicates over-decomposition; collapse to the original question.
            if len(result) > 2:
                return [question]
            # Collapse spurious splits: if no compound conjunction in the original
            # question, it should never need more than one sub-query.
            if len(result) > 1:
                q_lower = question.lower()
                if not any(c in q_lower for c in (" and ", " also ", " as well", " plus ")):
                    return [question]
            return result
        except Exception:
            return [question]
