"""Orchestrate a single research run end to end."""

from __future__ import annotations

import logging

from .agents import build_team
from .config import get_settings

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Raised when required configuration (e.g. the API key) is missing."""


def run_research(question: str) -> dict:
    """Run the multi-agent literature review for `question`.

    Returns a dict with `question`, `summary`, `paper_count`, `papers`,
    `json_path`, `markdown_path`. Raises `ConfigurationError` if the Anthropic
    API key is not configured.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ConfigurationError(
            "ANTHROPIC_API_KEY is not set. Add it to your environment or .env file."
        )

    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")

    researcher, proxy, tools = build_team(question, settings)

    logger.info("Starting research run for question: %s", question)
    proxy.initiate_chat(researcher, message=question, clear_history=True)

    report = tools.last_report
    if report is None:
        # The agents finished without producing a report (e.g. nothing relevant
        # found, or the turn cap was hit before saving).
        logger.warning("Research run ended without a saved report.")
        return {
            "question": question,
            "summary": "",
            "paper_count": 0,
            "papers": [],
            "json_path": None,
            "markdown_path": None,
            "saved": False,
        }

    return {
        "question": question,
        "summary": report.get("summary", ""),
        "paper_count": report.get("paper_count", 0),
        "papers": report.get("papers", []),
        "json_path": report.get("json_path"),
        "markdown_path": report.get("markdown_path"),
        "saved": True,
    }
