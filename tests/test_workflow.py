"""Tests for run orchestration (`app/workflow.py`).

`build_team` is stubbed out, so no agent is constructed and no API call is made.
"""

from __future__ import annotations

import pytest

from app import workflow
from app.workflow import ConfigurationError, run_research


class FakeProxy:
    """Stands in for the UserProxyAgent; records the chat it was asked to start."""

    def __init__(self, on_chat=None):
        self.chats: list[dict] = []
        self._on_chat = on_chat

    def initiate_chat(self, recipient, message, clear_history=True):
        self.chats.append({"message": message, "clear_history": clear_history})
        if self._on_chat:
            self._on_chat()


class FakeTools:
    def __init__(self, report=None, rejected=None):
        self.last_report = report
        self._rejected = rejected or []

    def top_rejected_journals(self, limit=10):
        return self._rejected[:limit]


@pytest.fixture
def stub_team(monkeypatch):
    """Install a fake team and return the call log."""

    def _install(report=None, rejected=None):
        calls: list[dict] = []
        proxy = FakeProxy()
        tools = FakeTools(report=None, rejected=rejected)

        def _build_team(question, settings=None, **kwargs):
            calls.append({"question": question, "settings": settings, **kwargs})
            # The report only exists once the chat has run.
            proxy._on_chat = lambda: setattr(tools, "last_report", report)
            return object(), proxy, tools

        monkeypatch.setattr(workflow, "build_team", _build_team)
        return calls, proxy

    return _install


REPORT = {
    "summary": "It depends.",
    "paper_count": 2,
    "papers": [{"title": "A"}, {"title": "B"}],
    "json_path": "output/x.json",
    "markdown_path": "output/x.md",
}


class TestConfigurationGuard:
    def test_a_missing_api_key_raises_before_any_work(self, monkeypatch, stub_team):
        calls, _ = stub_team(REPORT)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        from app.config import get_settings

        get_settings.cache_clear()

        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            run_research("Does fasting help?")
        assert calls == [], "no team should be built without a key"


@pytest.fixture
def _with_key(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("_with_key")
class TestQuestionHandling:
    @pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
    def test_a_blank_question_is_rejected(self, blank, stub_team):
        stub_team(REPORT)
        with pytest.raises(ValueError, match="must not be empty"):
            run_research(blank)

    def test_the_question_is_stripped(self, stub_team):
        calls, proxy = stub_team(REPORT)
        result = run_research("  Does fasting help?  ")
        assert calls[0]["question"] == "Does fasting help?"
        assert proxy.chats[0]["message"] == "Does fasting help?"
        assert result["question"] == "Does fasting help?"

    def test_history_is_cleared_so_runs_do_not_leak(self, stub_team):
        _, proxy = stub_team(REPORT)
        run_research("Does fasting help?")
        assert proxy.chats[0]["clear_history"] is True


@pytest.mark.usefixtures("_with_key")
class TestResultShape:
    def test_a_successful_run_returns_the_report(self, stub_team):
        stub_team(REPORT)
        result = run_research("Does fasting help?")
        assert result["saved"] is True
        assert result["summary"] == "It depends."
        assert result["paper_count"] == 2
        assert result["json_path"] == "output/x.json"

    def test_a_run_with_no_report_is_reported_honestly(self, stub_team):
        """Agents can finish without saving -- nothing relevant found, or the
        turn cap hit first. That must not look like a successful empty run."""
        stub_team(None)
        result = run_research("Does fasting help?")
        assert result["saved"] is False
        assert result["summary"] == ""
        assert result["paper_count"] == 0
        assert result["papers"] == []
        assert result["rejected_journals"] == []
        assert result["json_path"] is None
        assert result["markdown_path"] is None

    def test_a_no_report_run_still_explains_what_was_excluded(self, stub_team):
        """The most useful thing an empty run can say is which venues it turned
        away, so the user can widen the filter instead of guessing."""
        stub_team(None, rejected=[{"journal": "Journal of Dairy Science", "count": 7}])
        result = run_research("Does colostrum fat matter?")
        assert result["saved"] is False
        assert result["rejected_journals"] == [{"journal": "Journal of Dairy Science", "count": 7}]

    def test_a_partial_report_falls_back_to_defaults(self, stub_team):
        stub_team({"summary": "Only a summary."})
        result = run_research("Does fasting help?")
        assert result["saved"] is True
        assert result["paper_count"] == 0
        assert result["json_path"] is None

    def test_every_documented_key_is_present(self, stub_team):
        stub_team(REPORT)
        result = run_research("Does fasting help?")
        assert set(result) == {
            "question",
            "summary",
            "paper_count",
            "papers",
            "rejected_journals",
            "json_path",
            "markdown_path",
            "saved",
        }
