"""Tests for the HTTP surface (`app/server.py`).

`workflow.run_research` is monkeypatched throughout, so nothing here spends an
API call or touches the network. These tests cover the guardrails that stand
between a public URL and the owner's Anthropic bill.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import server
from app.journals import JOURNALS_BY_FIELD, UnknownFieldError
from app.limits import DailyRunLimiter
from app.workflow import ConfigurationError

RESULT = {
    "question": "Does fasting help?",
    "summary": "It depends.",
    "paper_count": 2,
    "papers": [{"title": "A"}, {"title": "B"}],
    "rejected_journals": [],
    "unmatched_journals": [],
    "verification": {},
    "json_path": "output/x.json",
    "markdown_path": "output/x.md",
    "saved": True,
}


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture
def stub_run(monkeypatch):
    """Replace the expensive agent run and record what it was called with."""
    calls: list[tuple[tuple, dict]] = []

    def _fake(*args, **kwargs):
        calls.append((args, kwargs))
        return dict(RESULT)

    monkeypatch.setattr(server, "run_research", _fake)
    return calls


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    """The limiter is module-level state; give each test its own."""
    monkeypatch.setattr(server, "_run_limiter", DailyRunLimiter(max_per_day=50))


class TestHealth:
    def test_reports_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestIndex:
    def test_serves_the_web_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "<html" in response.text.lower()


class TestConfig:
    def test_no_password_configured(self, client, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password=""))
        assert client.get("/config").json()["password_required"] is False

    def test_password_configured(self, client, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password="hunter2"))
        assert client.get("/config").json()["password_required"] is True


class TestResearchAccessGate:
    def test_runs_when_no_password_is_configured(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password=""))
        response = client.post("/research", json={"question": "Does fasting help?"})
        assert response.status_code == 200
        assert response.json()["summary"] == "It depends."
        assert len(stub_run) == 1

    def test_rejects_a_wrong_password(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password="hunter2"))
        response = client.post(
            "/research",
            json={"question": "Does fasting help?"},
            headers={"X-Access-Password": "wrong"},
        )
        assert response.status_code == 401
        assert stub_run == [], "the run must not start before the gate passes"

    def test_rejects_a_missing_password(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password="hunter2"))
        response = client.post("/research", json={"question": "Does fasting help?"})
        assert response.status_code == 401
        assert stub_run == []

    def test_accepts_the_right_password(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(access_password="hunter2"))
        response = client.post(
            "/research",
            json={"question": "Does fasting help?"},
            headers={"X-Access-Password": "hunter2"},
        )
        assert response.status_code == 200
        assert len(stub_run) == 1


class TestResearchValidation:
    def test_rejects_a_too_short_question(self, client, stub_run):
        assert client.post("/research", json={"question": "hi"}).status_code == 422
        assert stub_run == []

    def test_rejects_an_over_long_question(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "get_settings", lambda: _settings(max_question_chars=20))
        response = client.post("/research", json={"question": "x" * 21})
        assert response.status_code == 422
        assert "too long" in response.json()["detail"]
        assert stub_run == []

    def test_the_question_is_stripped_before_the_run(self, client, stub_run):
        client.post("/research", json={"question": "   Does fasting help?   "})
        assert stub_run[0][0][0] == "Does fasting help?"


class TestDailyRunLimit:
    def test_refuses_once_the_cap_is_reached(self, client, stub_run, monkeypatch):
        monkeypatch.setattr(server, "_run_limiter", DailyRunLimiter(max_per_day=1))
        first = client.post("/research", json={"question": "Does fasting help?"})
        second = client.post("/research", json={"question": "Does fasting help?"})
        assert first.status_code == 200
        assert second.status_code == 429
        assert len(stub_run) == 1

    def test_a_failed_run_gives_its_slot_back(self, client, monkeypatch):
        """A crash must not burn a slot -- nothing was billed."""

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        limiter = DailyRunLimiter(max_per_day=1)
        monkeypatch.setattr(server, "_run_limiter", limiter)
        monkeypatch.setattr(server, "run_research", _boom)
        assert client.post("/research", json={"question": "Does fasting help?"}).status_code == 500
        assert limiter.remaining == 1


class TestErrorMapping:
    def test_missing_api_key_is_a_503(self, client, monkeypatch):
        def _raise(*a, **k):
            raise ConfigurationError("ANTHROPIC_API_KEY is not set.")

        monkeypatch.setattr(server, "run_research", _raise)
        response = client.post("/research", json={"question": "Does fasting help?"})
        assert response.status_code == 503
        assert "ANTHROPIC_API_KEY" in response.json()["detail"]

    def test_a_bad_value_is_a_422(self, client, monkeypatch):
        def _raise(*a, **k):
            raise ValueError("question must not be empty")

        monkeypatch.setattr(server, "run_research", _raise)
        assert client.post("/research", json={"question": "Does fasting?"}).status_code == 422

    def test_an_unexpected_failure_is_a_500(self, client, monkeypatch):
        def _raise(*a, **k):
            raise RuntimeError("upstream exploded")

        monkeypatch.setattr(server, "run_research", _raise)
        response = client.post("/research", json={"question": "Does fasting help?"})
        assert response.status_code == 500
        assert "upstream exploded" in response.json()["detail"]


class TestResponseShape:
    def test_returns_every_documented_field(self, client, stub_run):
        body = client.post("/research", json={"question": "Does fasting help?"}).json()
        assert set(body) == {
            "question",
            "summary",
            "paper_count",
            "saved",
            "papers",
            "rejected_journals",
            "unmatched_journals",
            "verification",
            "json_path",
            "markdown_path",
        }

    def test_an_empty_run_is_reported_honestly(self, client, monkeypatch):
        empty = dict(RESULT, summary="", paper_count=0, papers=[], saved=False, json_path=None)
        monkeypatch.setattr(server, "run_research", lambda *a, **k: empty)
        body = client.post("/research", json={"question": "Does fasting help?"}).json()
        assert body["saved"] is False
        assert body["paper_count"] == 0


def _settings(**overrides):
    """A Settings instance with test-friendly defaults."""
    from app.config import Settings

    base = {
        "anthropic_api_key": "test-key",
        "access_password": "",
        "max_question_chars": 500,
        "max_runs_per_day": 50,
    }
    return Settings(**{**base, **overrides})


class TestJournalsEndpoint:
    def test_lists_every_field_exactly_once_across_the_groups(self, client):
        body = client.get("/journals").json()
        keys = [f["key"] for g in body["groups"] for f in g["fields"]]
        assert sorted(keys) == sorted(JOURNALS_BY_FIELD)
        assert len(keys) == len(set(keys)), "a field appears in two groups"

    def test_each_field_carries_a_label_count_and_examples(self, client):
        body = client.get("/journals").json()
        for group in body["groups"]:
            assert group["name"]
            for entry in group["fields"]:
                assert entry["label"]
                assert entry["count"] == len(JOURNALS_BY_FIELD[entry["key"]])
                assert len(entry["examples"]) <= 3

    def test_reports_the_totals(self, client):
        body = client.get("/journals").json()
        assert body["total_fields"] == len(JOURNALS_BY_FIELD)
        assert body["total_journals"] == len(set().union(*JOURNALS_BY_FIELD.values()))

    def test_group_order_is_stable(self, client):
        """The UI renders groups in this order, so it must not depend on a set."""
        first = [g["name"] for g in client.get("/journals").json()["groups"]]
        second = [g["name"] for g in client.get("/journals").json()["groups"]]
        assert first == second


class TestConfigHints:
    def test_exposes_the_limits_the_page_would_otherwise_hardcode(self, client, monkeypatch):
        monkeypatch.setattr(
            server, "get_settings", lambda: _settings(min_year=2019, max_question_chars=300)
        )
        body = client.get("/config").json()
        assert body["min_year"] == 2019
        assert body["max_question_chars"] == 300
        assert body["earliest_year"] == server.EARLIEST_YEAR


class TestJournalSelection:
    def test_fields_and_min_year_reach_the_run(self, client, stub_run):
        client.post(
            "/research",
            json={
                "question": "Does colostrum fat matter?",
                "fields": ["agriculture_food"],
                "min_year": 2018,
            },
        )
        kwargs = stub_run[0][1]
        assert kwargs["fields"] == ["agriculture_food"]
        assert kwargs["min_year"] == 2018

    def test_extra_journals_are_trimmed_and_passed_through(self, client, stub_run):
        client.post(
            "/research",
            json={
                "question": "Does colostrum fat matter?",
                "extra_journals": ["  Poultry Weekly  ", "", "   "],
            },
        )
        assert stub_run[0][1]["extra_journals"] == ["Poultry Weekly"]

    def test_omitting_the_controls_leaves_them_unset(self, client, stub_run):
        client.post("/research", json={"question": "Does fasting help?"})
        kwargs = stub_run[0][1]
        assert kwargs["fields"] is None
        assert kwargs["min_year"] is None

    def test_an_unknown_field_is_a_422(self, client, monkeypatch):
        """UnknownFieldError subclasses ValueError, which the handler maps to 422."""

        def _raise(*args, **kwargs):
            raise UnknownFieldError("Unknown field(s): astrology.")

        monkeypatch.setattr(server, "run_research", _raise)
        response = client.post(
            "/research", json={"question": "Does fasting help?", "fields": ["astrology"]}
        )
        assert response.status_code == 422
        assert "astrology" in response.json()["detail"]


class TestJournalControlValidation:
    @pytest.mark.parametrize("year", [1899, 3000])
    def test_an_out_of_range_min_year_is_rejected(self, client, stub_run, year):
        response = client.post(
            "/research", json={"question": "Does fasting help?", "min_year": year}
        )
        assert response.status_code == 422
        assert "min_year" in response.json()["detail"]
        assert stub_run == [], "validation must happen before the run starts"

    def test_the_current_year_is_allowed(self, client, stub_run):
        this_year = datetime.now(timezone.utc).year
        response = client.post(
            "/research", json={"question": "Does fasting help?", "min_year": this_year}
        )
        assert response.status_code == 200

    def test_too_many_extra_journals_are_rejected(self, client, stub_run):
        response = client.post(
            "/research",
            json={
                "question": "Does fasting help?",
                "extra_journals": [f"Journal {i}" for i in range(server.MAX_EXTRA_JOURNALS + 1)],
            },
        )
        assert response.status_code == 422
        assert stub_run == []

    def test_an_over_long_journal_name_is_rejected(self, client, stub_run):
        response = client.post(
            "/research",
            json={
                "question": "Does fasting help?",
                "extra_journals": ["x" * (server.MAX_JOURNAL_NAME_CHARS + 1)],
            },
        )
        assert response.status_code == 422
        assert stub_run == []

    def test_no_fields_and_no_extras_is_rejected(self, client, stub_run):
        """That combination can only ever return nothing — say so up front
        rather than spending a run to discover it."""
        response = client.post("/research", json={"question": "Does fasting help?", "fields": []})
        assert response.status_code == 422
        assert "No journals selected" in response.json()["detail"]
        assert stub_run == []

    def test_no_fields_but_named_journals_is_allowed(self, client, stub_run):
        response = client.post(
            "/research",
            json={
                "question": "Does fasting help?",
                "fields": [],
                "extra_journals": ["Poultry Weekly"],
            },
        )
        assert response.status_code == 200
        assert stub_run[0][1]["fields"] == []

    def test_a_rejected_request_does_not_consume_a_run_slot(self, client, monkeypatch):
        limiter = DailyRunLimiter(max_per_day=1)
        monkeypatch.setattr(server, "_run_limiter", limiter)
        client.post("/research", json={"question": "Does fasting help?", "min_year": 1500})
        assert limiter.remaining == 1


class TestRejectedJournalsInTheResponse:
    def test_exclusions_are_returned_to_the_caller(self, client, monkeypatch):
        rejected = [{"journal": "Journal of Dairy Science", "count": 7}]
        empty = dict(RESULT, papers=[], paper_count=0, saved=False, rejected_journals=rejected)
        monkeypatch.setattr(server, "run_research", lambda *a, **k: empty)
        body = client.post("/research", json={"question": "Does colostrum fat matter?"}).json()
        assert body["rejected_journals"] == rejected

    def test_defaults_to_an_empty_list(self, client, stub_run):
        body = client.post("/research", json={"question": "Does fasting help?"}).json()
        assert body["rejected_journals"] == []
