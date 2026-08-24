"""Orchestrate a single research run end to end."""

from __future__ import annotations

import logging

from .agents import build_team
from .config import get_settings
from .journals import JournalPolicy

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Raised when required configuration (e.g. the API key) is missing."""


def run_research(
    question: str,
    *,
    fields: list[str] | None = None,
    extra_journals: list[str] | None = None,
    min_year: int | None = None,
) -> dict:
    """Run the multi-agent literature review for `question`.

    Args:
        question: The research question to answer.
        fields: Journal field keys to restrict the search to (see
            `app.journals.JOURNALS_BY_FIELD`). `None` means every field.
        extra_journals: Additional journal titles to accept, on top of `fields`.
        min_year: Earliest publication year. Defaults to `settings.min_year`.

    Returns a dict with `question`, `summary`, `paper_count`, `papers`,
    `rejected_journals`, `json_path`, `markdown_path`, `saved`.

    Raises:
        ConfigurationError: if the Anthropic API key is not configured.
        ValueError: if the question is blank or a field key is unknown
            (`UnknownFieldError` is a `ValueError`).
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ConfigurationError(
            "ANTHROPIC_API_KEY is not set. Add it to your environment or .env file."
        )

    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")

    # Raises UnknownFieldError (a ValueError) on a bad field key, before any
    # API call is made.
    policy = JournalPolicy.build(fields=fields, extra_journals=extra_journals)

    researcher, proxy, tools = build_team(question, settings, policy=policy, min_year=min_year)

    logger.info(
        "Starting research run for question: %s (journals: %s)", question, policy.describe()
    )
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
            # Even with nothing saved, the excluded journals explain why.
            "rejected_journals": tools.top_rejected_journals(),
            "json_path": None,
            "markdown_path": None,
            "saved": False,
        }

    return {
        "question": question,
        "summary": report.get("summary", ""),
        "paper_count": report.get("paper_count", 0),
        "papers": report.get("papers", []),
        "rejected_journals": report.get("rejected_journals", []),
        "json_path": report.get("json_path"),
        "markdown_path": report.get("markdown_path"),
        "saved": True,
    }
