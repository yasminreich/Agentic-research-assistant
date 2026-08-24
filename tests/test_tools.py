"""Tests for the functions the agents actually call (`app/tools.py`).

`ResearchTools` accepts an injected client, so the whole
search -> filter -> dedup -> JSON path runs offline.
"""

from __future__ import annotations

import json

import pytest

from app.journals import JournalPolicy
from app.openalex_client import OpenAlexError
from app.tools import ABSTRACT_PREVIEW_CHARS, ResearchTools


class FakeClient:
    """Returns a canned paper list and records the search arguments."""

    def __init__(self, papers=None, error=None):
        self._papers = papers or []
        self._error = error
        self.calls: list[dict] = []

    def search(self, query, *, limit=50, year_from=None):
        self.calls.append({"query": query, "limit": limit, "year_from": year_from})
        if self._error:
            raise self._error
        return list(self._papers)


@pytest.fixture
def tools_for():
    def _build(papers=None, error=None, question="Does fasting help?"):
        client = FakeClient(papers=papers, error=error)
        return ResearchTools(question=question, client=client), client

    return _build


class TestSearchLiterature:
    def test_returns_curated_candidates_as_json(self, tools_for, make_paper):
        tools, _ = tools_for([make_paper("Fasting works", journal_name="Nature", year=2020)])
        payload = json.loads(tools.search_literature("fasting"))
        assert payload["query"] == "fasting"
        assert payload["curated_count"] == 1
        assert payload["papers"][0]["title"] == "Fasting works"
        assert payload["papers"][0]["journal"] == "Nature"

    def test_reports_the_funnel_at_each_stage(self, tools_for, make_paper):
        papers = [
            make_paper("Kept", journal_name="Nature", year=2020),
            make_paper("Kept", journal_name="Nature", year=2022),  # duplicate title
            make_paper("Filtered out", journal_name="Journal of Nowhere"),
        ]
        tools, _ = tools_for(papers)
        payload = json.loads(tools.search_literature("q"))
        assert payload["total_retrieved"] == 3
        assert payload["high_impact_count"] == 2
        assert payload["curated_count"] == 1

    def test_the_newest_of_a_duplicate_pair_survives(self, tools_for, make_paper):
        papers = [
            make_paper("Same study", journal_name="Cell", year=2016),
            make_paper("Same study", journal_name="Cell", year=2023),
        ]
        tools, _ = tools_for(papers)
        payload = json.loads(tools.search_literature("q"))
        assert payload["papers"][0]["year"] == 2023

    def test_abstracts_are_truncated_for_the_prompt(self, tools_for, make_paper):
        long_abstract = "word " * 2000
        tools, _ = tools_for([make_paper(journal_name="Nature", abstract=long_abstract)])
        payload = json.loads(tools.search_literature("q"))
        assert len(payload["papers"][0]["abstract"]) == ABSTRACT_PREVIEW_CHARS

    def test_a_missing_abstract_becomes_an_empty_string(self, tools_for, make_paper):
        tools, _ = tools_for([make_paper(journal_name="Nature", abstract=None)])
        payload = json.loads(tools.search_literature("q"))
        assert payload["papers"][0]["abstract"] == ""

    def test_full_metadata_is_retained_for_the_save_step(self, tools_for, make_paper):
        paper = make_paper("Fasting works", journal_name="Nature", paper_id="W7")
        tools, _ = tools_for([paper])
        tools.search_literature("q")
        assert "W7" in tools.collected
        assert tools.collected["W7"]["authors"] == paper.authors

    def test_defaults_come_from_settings(self, tools_for):
        tools, client = tools_for()
        tools.search_literature("q")
        assert client.calls[0]["year_from"] == tools.settings.min_year
        assert client.calls[0]["limit"] == tools.settings.max_papers_per_query

    def test_explicit_arguments_win(self, tools_for):
        tools, client = tools_for()
        tools.search_literature("q", year_from=2021, limit=7)
        assert client.calls[0] == {"query": "q", "limit": 7, "year_from": 2021}

    def test_an_api_failure_is_reported_not_raised(self, tools_for):
        """The agent must see an error it can react to, not a crashed tool call."""
        tools, _ = tools_for(error=OpenAlexError("upstream down"))
        payload = json.loads(tools.search_literature("q"))
        assert payload["papers"] == []
        assert "upstream down" in payload["error"]

    def test_no_high_impact_matches_yields_an_empty_list(self, tools_for, make_paper):
        tools, _ = tools_for([make_paper(journal_name="Journal of Nowhere")])
        payload = json.loads(tools.search_literature("q"))
        assert payload["total_retrieved"] == 1
        assert payload["papers"] == []


class TestSaveResearchReport:
    def test_resolves_ids_and_writes_the_report(self, tools_for, make_paper, tmp_path):
        tools, _ = tools_for([make_paper("Fasting works", journal_name="Nature", paper_id="W1")])
        tools.search_literature("q")

        message = tools.save_research_report("The summary.", ["W1"], "Does fasting help?")

        assert "1 papers" in message
        assert tools.last_report is not None
        assert tools.last_report["paper_count"] == 1
        assert tools.last_report["summary"] == "The summary."
        assert tools.last_report["papers"][0]["title"] == "Fasting works"

    def test_unknown_ids_are_skipped_rather_than_crashing(self, tools_for, make_paper):
        """The model can hallucinate an id; that must not take down the run."""
        tools, _ = tools_for([make_paper(journal_name="Nature", paper_id="W1")])
        tools.search_literature("q")
        tools.save_research_report("S", ["W1", "W-does-not-exist"], "Q")
        assert tools.last_report["paper_count"] == 1

    def test_falls_back_to_the_run_question(self, tools_for):
        tools, _ = tools_for(question="The original question")
        tools.save_research_report("S", [], "")
        assert "the-original-question" in tools.last_report["json_path"]

    def test_saving_with_no_papers_still_produces_a_report(self, tools_for):
        tools, _ = tools_for()
        tools.save_research_report("Nothing relevant found.", [], "Q")
        assert tools.last_report["paper_count"] == 0

    def test_last_report_is_none_before_saving(self, tools_for):
        tools, _ = tools_for()
        assert tools.last_report is None


class TestJournalPolicyIntegration:
    def test_a_narrowed_policy_is_applied_to_results(self, make_paper):
        policy = JournalPolicy.build(fields=["agriculture_food"])
        papers = [
            make_paper("Dairy work", journal_name="Journal of Dairy Science"),
            make_paper("Physics work", journal_name="Nature"),
        ]
        tools = ResearchTools(question="Q", client=FakeClient(papers), policy=policy)
        payload = json.loads(tools.search_literature("q"))
        assert [p["title"] for p in payload["papers"]] == ["Dairy work"]

    def test_the_policy_is_described_for_the_agent(self, make_paper):
        policy = JournalPolicy.build(fields=["agriculture_food"])
        tools = ResearchTools(question="Q", client=FakeClient([]), policy=policy)
        payload = json.loads(tools.search_literature("q"))
        assert payload["journal_policy"] == "Agriculture & food science"

    def test_min_year_overrides_the_settings_default(self):
        client = FakeClient([])
        tools = ResearchTools(question="Q", client=client, min_year=2021)
        tools.search_literature("q")
        assert client.calls[0]["year_from"] == 2021

    def test_an_explicit_year_from_still_wins_over_min_year(self):
        client = FakeClient([])
        tools = ResearchTools(question="Q", client=client, min_year=2021)
        tools.search_literature("q", year_from=2010)
        assert client.calls[0]["year_from"] == 2010


class TestRejectedJournalReporting:
    def test_excluded_journals_are_reported_in_the_search_payload(self, make_paper):
        papers = [make_paper(journal_name="Nowhere Journal") for _ in range(3)]
        tools = ResearchTools(question="Q", client=FakeClient(papers))
        payload = json.loads(tools.search_literature("q"))
        assert payload["papers"] == []
        assert payload["rejected_journals"] == [{"journal": "Nowhere Journal", "count": 3}]

    def test_counts_accumulate_across_several_searches(self, make_paper):
        papers = [make_paper(journal_name="Nowhere Journal")]
        tools = ResearchTools(question="Q", client=FakeClient(papers))
        tools.search_literature("first")
        tools.search_literature("second")
        assert tools.top_rejected_journals() == [{"journal": "Nowhere Journal", "count": 2}]

    def test_the_saved_report_carries_the_exclusions(self, make_paper):
        """A run that finds nothing should still be able to say why."""
        papers = [make_paper(journal_name="Journal of Dairy Science")]
        policy = JournalPolicy.build(fields=["physics"])
        tools = ResearchTools(question="Q", client=FakeClient(papers), policy=policy)
        tools.search_literature("q")
        tools.save_research_report("Nothing found.", [], "Q")
        assert tools.last_report["rejected_journals"] == [
            {"journal": "Journal of Dairy Science", "count": 1}
        ]

    def test_nothing_is_reported_when_everything_passed(self, make_paper):
        tools = ResearchTools(question="Q", client=FakeClient([make_paper(journal_name="Nature")]))
        tools.search_literature("q")
        assert tools.top_rejected_journals() == []


class TestUnmatchedJournals:
    def test_a_named_journal_with_no_papers_is_reported(self, make_paper):
        """A misspelled journal used to fail completely silently."""
        policy = JournalPolicy.build(fields=["medicine"], extra_journals=["Gut Microbs"])
        tools = ResearchTools(
            question="Q", client=FakeClient([make_paper(journal_name="Nature")]), policy=policy
        )
        tools.search_literature("q")
        assert tools.unmatched_journals() == ["gut microbs"]

    def test_a_named_journal_that_did_appear_is_not_reported(self, make_paper):
        policy = JournalPolicy.build(fields=[], extra_journals=["Gut Microbes"])
        papers = [make_paper(journal_name="Gut Microbes")]
        tools = ResearchTools(question="Q", client=FakeClient(papers), policy=policy)
        tools.search_literature("q")
        assert tools.unmatched_journals() == []

    def test_it_counts_papers_the_policy_rejected_too(self, make_paper):
        """Seeing the journal at all is what matters — a paper dropped by the
        year filter still proves the name was spelled right."""
        policy = JournalPolicy.build(fields=["medicine"], extra_journals=["Nutrients"])
        tools = ResearchTools(
            question="Q", client=FakeClient([make_paper(journal_name="Nutrients")]), policy=policy
        )
        tools.search_literature("q")
        assert tools.unmatched_journals() == []

    def test_nothing_named_means_nothing_reported(self, make_paper):
        tools = ResearchTools(question="Q", client=FakeClient([make_paper(journal_name="Nature")]))
        tools.search_literature("q")
        assert tools.unmatched_journals() == []

    def test_the_saved_report_carries_it(self, make_paper):
        policy = JournalPolicy.build(fields=["medicine"], extra_journals=["Gut Microbs"])
        tools = ResearchTools(
            question="Q", client=FakeClient([make_paper(journal_name="Nature")]), policy=policy
        )
        tools.search_literature("q")
        tools.save_research_report("S", [], "Q")
        assert tools.last_report["unmatched_journals"] == ["gut microbs"]


class TestVerificationIntegration:
    """The tool layer must run the checks and attach the results."""

    ABSTRACT = (
        "Gut microbiota regulate host immune development through short-chain fatty "
        "acids. We profiled 240 stool samples and found that butyrate producers were "
        "depleted in patients with active disease."
    )
    REAL_QUOTE = "We profiled 240 stool samples and found that butyrate producers were depleted"

    def _tools(self, make_paper):
        paper = make_paper(
            "Microbiota and immunity",
            journal_name="Nature",
            paper_id="W111111",
            abstract=self.ABSTRACT,
        )
        return ResearchTools(question="Q", client=FakeClient([paper]))

    def test_a_faithful_report_verifies_clean(self, make_paper):
        tools = self._tools(make_paper)
        tools.search_literature("q")
        tools.save_research_report(
            "Butyrate producers are depleted (W111111).",
            ["W111111"],
            "Q",
            [{"paper_id": "W111111", "quote": self.REAL_QUOTE}],
        )
        v = tools.last_report["verification"]
        assert v["ok"] is True
        assert v["citations"]["verified_count"] == 1
        assert v["quotes"]["tally"]["supported"] == 1

    def test_an_invented_citation_is_caught(self, make_paper):
        """The model cites a paper no search ever returned."""
        tools = self._tools(make_paper)
        tools.search_literature("q")
        tools.save_research_report("As established elsewhere (W9999999).", ["W111111"], "Q", [])
        v = tools.last_report["verification"]
        assert v["ok"] is False
        assert v["citations"]["unverified"] == ["W9999999"]

    def test_an_invented_quote_is_caught(self, make_paper):
        """The citation is real but the finding attributed to it is not."""
        tools = self._tools(make_paper)
        tools.search_literature("q")
        tools.save_research_report(
            "Butyrate cures the disease outright (W111111).",
            ["W111111"],
            "Q",
            [{"paper_id": "W111111", "quote": "Butyrate cured every patient within a week"}],
        )
        v = tools.last_report["verification"]
        assert v["ok"] is False
        assert v["quotes"]["tally"]["not_found"] == 1

    def test_a_dropped_paper_id_is_surfaced_not_just_logged(self, make_paper):
        tools = self._tools(make_paper)
        tools.search_literature("q")
        tools.save_research_report("Summary (W111111).", ["W111111", "W888888"], "Q", [])
        assert tools.last_report["verification"]["unknown_paper_ids"] == ["W888888"]

    def test_quotes_are_attached_to_their_paper(self, make_paper):
        """So the UI and the Markdown report can show evidence beside the source."""
        tools = self._tools(make_paper)
        tools.search_literature("q")
        tools.save_research_report(
            "Summary (W111111).",
            ["W111111"],
            "Q",
            [{"paper_id": "W111111", "quote": self.REAL_QUOTE}],
        )
        paper = tools.last_report["papers"][0]
        assert paper["evidence"][0]["status"] == "supported"

    def test_evidence_is_optional(self, make_paper):
        """A run that supplies no quotes must still save and verify citations."""
        tools = self._tools(make_paper)
        tools.search_literature("q")
        tools.save_research_report("Summary (W111111).", ["W111111"], "Q")
        assert tools.last_report["verification"]["ok"] is True
