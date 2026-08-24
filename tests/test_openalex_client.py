"""Tests for the OpenAlex client (`app/openalex_client.py`).

No network: every test injects a fake `requests.Session`, the seam the client
already exposed via its `session=` constructor argument.
"""

from __future__ import annotations

import pytest
import requests

from app.openalex_client import MAX_LIMIT, OpenAlexClient, OpenAlexError

# A trimmed but realistically shaped OpenAlex work record.
WORK = {
    "id": "https://openalex.org/W123",
    "display_name": "  Fasting and insulin sensitivity  ",
    "publication_year": 2018,
    "cited_by_count": 42,
    "doi": "https://doi.org/10.1016/j.cmet.2018.04.010",
    "primary_location": {
        "source": {"display_name": "Cell Metabolism"},
        "landing_page_url": "https://example.org/paper",
    },
    "authorships": [
        {"author": {"display_name": "Ada Lovelace"}},
        {"author": {"display_name": "Grace Hopper"}},
    ],
    "abstract_inverted_index": {"Fasting": [0], "improves": [1], "insulin": [2]},
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"results": []}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    """Replays a queued list of responses (or exceptions) and records requests."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Backoff must not actually sleep, or the retry tests would take ~30s."""
    slept: list[float] = []
    monkeypatch.setattr("app.openalex_client.time.sleep", slept.append)
    return slept


def make_client(responses, **kwargs):
    return OpenAlexClient(mailto="", session=FakeSession(responses), **kwargs)


class TestReconstructAbstract:
    def test_rebuilds_words_in_position_order(self):
        index = {"world": [1], "Hello": [0], "again": [2]}
        assert OpenAlexClient._reconstruct_abstract(index) == "Hello world again"

    def test_a_repeated_word_appears_at_every_position(self):
        index = {"the": [0, 2], "cat": [1], "sat": [3]}
        assert OpenAlexClient._reconstruct_abstract(index) == "the cat the sat"

    @pytest.mark.parametrize("empty", [None, {}])
    def test_absent_index_yields_none(self, empty):
        assert OpenAlexClient._reconstruct_abstract(empty) is None


class TestNormalize:
    def test_maps_a_full_record(self):
        paper = OpenAlexClient._normalize(WORK)
        assert paper.paper_id == "https://openalex.org/W123"
        assert paper.title == "Fasting and insulin sensitivity"  # stripped
        assert paper.year == 2018
        assert paper.citation_count == 42
        assert paper.journal_name == "Cell Metabolism"
        assert paper.authors == ["Ada Lovelace", "Grace Hopper"]
        assert paper.abstract == "Fasting improves insulin"
        assert paper.url == "https://example.org/paper"

    def test_strips_the_doi_url_prefix(self):
        assert OpenAlexClient._normalize(WORK).doi == "10.1016/j.cmet.2018.04.010"

    def test_missing_primary_location_is_survivable(self):
        paper = OpenAlexClient._normalize({"id": "W1", "display_name": "T"})
        assert paper.journal_name is None
        assert paper.citation_count == 0
        assert paper.authors == []
        assert paper.url == "W1"

    def test_null_primary_location_is_survivable(self):
        paper = OpenAlexClient._normalize(
            {"id": "W1", "display_name": "T", "primary_location": None}
        )
        assert paper.journal_name is None

    def test_authorships_without_a_name_are_skipped(self):
        record = dict(WORK, authorships=[{"author": {}}, {"author": {"display_name": "Ada"}}, {}])
        assert OpenAlexClient._normalize(record).authors == ["Ada"]

    def test_venue_and_journal_name_agree(self):
        paper = OpenAlexClient._normalize(WORK)
        assert paper.venue == paper.journal_name


class TestSearch:
    def test_returns_normalized_papers(self):
        client = make_client([FakeResponse(payload={"results": [WORK]})])
        papers = client.search("fasting")
        assert len(papers) == 1
        assert papers[0].journal_name == "Cell Metabolism"

    def test_drops_records_with_no_title(self):
        untitled = dict(WORK, display_name="")
        client = make_client([FakeResponse(payload={"results": [WORK, untitled]})])
        assert len(client.search("fasting")) == 1

    def test_missing_results_key_yields_empty_list(self):
        client = make_client([FakeResponse(payload={})])
        assert client.search("fasting") == []

    def test_sends_the_query_and_year_filter(self):
        session = FakeSession([FakeResponse()])
        OpenAlexClient(mailto="", session=session).search("fasting", year_from=2019)
        params = session.calls[0]["params"]
        assert params["search"] == "fasting"
        assert "from_publication_date:2019-01-01" in params["filter"]
        assert "type:article" in params["filter"]

    def test_omits_the_year_filter_when_not_given(self):
        session = FakeSession([FakeResponse()])
        OpenAlexClient(mailto="", session=session).search("fasting")
        assert "from_publication_date" not in session.calls[0]["params"]["filter"]

    def test_limit_is_clamped_to_the_api_maximum(self):
        session = FakeSession([FakeResponse()])
        OpenAlexClient(mailto="", session=session).search("q", limit=99_999)
        assert session.calls[0]["params"]["per-page"] == MAX_LIMIT

    def test_limit_is_floored_at_one(self):
        session = FakeSession([FakeResponse()])
        OpenAlexClient(mailto="", session=session).search("q", limit=0)
        assert session.calls[0]["params"]["per-page"] == 1

    def test_mailto_is_sent_when_configured(self):
        session = FakeSession([FakeResponse()])
        OpenAlexClient(mailto="me@example.org", session=session).search("q")
        assert session.calls[0]["params"]["mailto"] == "me@example.org"

    def test_mailto_is_omitted_when_blank(self):
        session = FakeSession([FakeResponse()])
        OpenAlexClient(mailto="", session=session).search("q")
        assert "mailto" not in session.calls[0]["params"]


class TestRetryBehaviour:
    def test_retries_after_a_429_then_succeeds(self, no_real_sleeping):
        session = FakeSession(
            [FakeResponse(429, text="slow down"), FakeResponse(payload={"results": [WORK]})]
        )
        papers = OpenAlexClient(mailto="", session=session).search("q")
        assert len(papers) == 1
        assert len(session.calls) == 2
        assert no_real_sleeping, "expected a backoff sleep between attempts"

    def test_honours_retry_after(self, no_real_sleeping):
        session = FakeSession(
            [FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(payload={"results": []})]
        )
        OpenAlexClient(mailto="", session=session).search("q")
        assert no_real_sleeping == [7]

    def test_caps_a_huge_retry_after(self, no_real_sleeping):
        session = FakeSession(
            [
                FakeResponse(429, headers={"Retry-After": "9999"}),
                FakeResponse(payload={"results": []}),
            ]
        )
        OpenAlexClient(mailto="", session=session).search("q")
        assert no_real_sleeping == [30]

    def test_retries_transient_5xx(self):
        session = FakeSession([FakeResponse(503), FakeResponse(payload={"results": [WORK]})])
        assert len(OpenAlexClient(mailto="", session=session).search("q")) == 1

    def test_retries_network_errors(self):
        session = FakeSession(
            [requests.ConnectionError("boom"), FakeResponse(payload={"results": [WORK]})]
        )
        assert len(OpenAlexClient(mailto="", session=session).search("q")) == 1

    def test_gives_up_after_max_retries(self):
        session = FakeSession([FakeResponse(500)] * 3)
        client = OpenAlexClient(mailto="", session=session, max_retries=2)
        with pytest.raises(OpenAlexError, match="after 3 attempts"):
            client.search("q")
        assert len(session.calls) == 3

    def test_client_errors_are_not_retried(self):
        session = FakeSession([FakeResponse(400, text="bad query")])
        with pytest.raises(OpenAlexError, match="400"):
            OpenAlexClient(mailto="", session=session).search("q")
        assert len(session.calls) == 1
