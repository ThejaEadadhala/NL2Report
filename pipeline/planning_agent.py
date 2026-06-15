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
    "Given a database schema and a user's analytical question, decide if the question "
    "needs to be broken into multiple sub-questions or can be answered by a single SQL query.\n\n"
    "CRITICAL RULE: Most questions need only ONE query. Only split if the question contains "
    "clearly separate analytical goals joined by 'and', 'also', 'as well as', or asks for "
    "two logically independent things (e.g. 'total sales by region AND which region had the highest growth').\n\n"
    "If the question asks for a single fact, count, list, or grouped result — return it as ONE element.\n"
    "Examples that must return ONE element:\n"
    "  [\"How many schools are in Alameda county?\"]\n"
    "  [\"What is the average account balance by market segment?\"]\n"
    "Examples that should be split:\n"
    "  [\"What are total sales by region?\", \"Which region had the highest growth?\"]\n\n"
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
            raw = self._model._generate(_SYSTEM_PROMPT, user)
            return _parse(raw, question)
        except Exception:
            return [question]
