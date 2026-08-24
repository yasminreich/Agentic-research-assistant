"""Shared fixtures.

Every test in this suite is offline: no network calls and no ANTHROPIC_API_KEY.
The two seams that make that possible already existed in the app —
`PaperclipClient` accepts an injected `requests.Session`, and `ResearchTools`
accepts an injected client.
"""

from __future__ import annotations

import pytest

from app.paperclip_client import Paper


@pytest.fixture
def make_paper():
    """Factory for `Paper` instances with sensible defaults.

    Only override what a given test actually cares about:
        make_paper(title="X", journal_name="Nature", year=2020)
    """
    counter = {"n": 0}

    def _make(
        title: str = "A study of things",
        *,
        journal_name: str | None = "Nature",
        year: int | None = 2020,
        citation_count: int = 0,
        paper_id: str | None = None,
        doi: str | None = None,
        abstract: str | None = "An abstract.",
        authors: list[str] | None = None,
        url: str | None = None,
    ) -> Paper:
        counter["n"] += 1
        return Paper(
            paper_id=paper_id if paper_id is not None else f"W{counter['n']}",
            title=title,
            abstract=abstract,
            year=year,
            venue=journal_name,
            journal_name=journal_name,
            citation_count=citation_count,
            authors=authors if authors is not None else ["Ada Lovelace"],
            doi=doi,
            url=url,
        )

    return _make


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch, tmp_path):
    """Keep tests from reading the developer's real `.env` or writing to `output/`.

    `get_settings()` is `@lru_cache`d, so the cache is cleared before and after
    each test to stop values leaking between them.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ACCESS_PASSWORD", "")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    yield
    get_settings.cache_clear()
