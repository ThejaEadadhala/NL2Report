"""
report_evaluator.py
Measures report generation quality using BLEU and ROUGE scores.
Used once the pipeline generates natural language reports alongside SQL results.

Requires: pip install nltk rouge-score
"""

from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from nltk.tokenize import word_tokenize
from rouge_score import rouge_scorer


def _tokenize(text: str) -> list[str]:
    return word_tokenize(text.lower())


def bleu_score(reference: str, hypothesis: str) -> float:
    """Sentence-level BLEU score (0.0 – 1.0)."""
    ref_tokens = _tokenize(reference)
    hyp_tokens = _tokenize(hypothesis)
    smoother = SmoothingFunction().method1
    return round(sentence_bleu([ref_tokens], hyp_tokens, smoothing_function=smoother), 4)


def rouge_scores(reference: str, hypothesis: str) -> dict:
    """ROUGE-1, ROUGE-2, and ROUGE-L F1 scores."""
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    scores = scorer.score(reference, hypothesis)
    return {
        "rouge1": round(scores["rouge1"].fmeasure, 4),
        "rouge2": round(scores["rouge2"].fmeasure, 4),
        "rougeL": round(scores["rougeL"].fmeasure, 4),
    }


def evaluate_report(reference: str, hypothesis: str) -> dict:
    """Return all report quality metrics for a single reference/hypothesis pair."""
    return {
        "bleu": bleu_score(reference, hypothesis),
        **rouge_scores(reference, hypothesis),
    }


def evaluate_reports(pairs: list[tuple[str, str]]) -> dict:
    """
    Average scores over multiple (reference, hypothesis) pairs.
    pairs: list of (reference, hypothesis) tuples
    """
    if not pairs:
        return {"bleu": 0, "rouge1": 0, "rouge2": 0, "rougeL": 0}

    totals = {"bleu": 0.0, "rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}
    for ref, hyp in pairs:
        scores = evaluate_report(ref, hyp)
        for k in totals:
            totals[k] += scores[k]

    n = len(pairs)
    return {k: round(v / n, 4) for k, v in totals.items()}
