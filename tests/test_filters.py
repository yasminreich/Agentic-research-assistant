"""Tests for the deterministic post-processing steps (`app/filters.py`)."""

from __future__ import annotations

from app.filters import (
    TITLE_SIMILARITY_THRESHOLD,
    deduplicate_by_recency,
    filter_high_impact,
    rejected_journal_counts,
)
from app.journals import JournalPolicy


class TestFilterHighImpact:
    def test_keeps_allowlisted_and_drops_the_rest(self, make_paper):
        papers = [
            make_paper("Kept", journal_name="Nature"),
            make_paper("Dropped", journal_name="Journal of Obscure Results"),
            make_paper("Also kept", journal_name="PNAS"),
        ]
        titles = [p.title for p in filter_high_impact(papers)]
        assert titles == ["Kept", "Also kept"]

    def test_drops_papers_with_no_journal(self, make_paper):
        assert filter_high_impact([make_paper(journal_name=None)]) == []

    def test_empty_input(self):
        assert filter_high_impact([]) == []

    def test_preserves_input_order(self, make_paper):
        papers = [make_paper(f"P{i}", journal_name="Cell") for i in range(5)]
        assert [p.title for p in filter_high_impact(papers)] == [f"P{i}" for i in range(5)]


class TestDeduplicateByRecency:
    def test_distinct_papers_all_survive(self, make_paper):
        papers = [make_paper("Alpha study"), make_paper("Beta trial"), make_paper("Gamma review")]
        assert len(deduplicate_by_recency(papers)) == 3

    def test_same_paper_id_collapses(self, make_paper):
        papers = [
            make_paper("Old title", paper_id="W1", year=2018),
            make_paper("Different wording entirely", paper_id="W1", year=2022),
        ]
        result = deduplicate_by_recency(papers)
        assert len(result) == 1
        assert result[0].year == 2022

    def test_shared_doi_collapses(self, make_paper):
        papers = [
            make_paper("Preprint version", paper_id="W1", doi="10.1/abc", year=2019),
            make_paper("Published version", paper_id="W2", doi="10.1/abc", year=2021),
        ]
        result = deduplicate_by_recency(papers)
        assert len(result) == 1
        assert result[0].year == 2021

    def test_near_identical_titles_collapse(self, make_paper):
        papers = [
            make_paper("Effects of fasting on insulin sensitivity", year=2017),
            make_paper("Effects of fasting on insulin sensitivity.", year=2021),
        ]
        result = deduplicate_by_recency(papers)
        assert len(result) == 1
        assert result[0].year == 2021

    def test_distinct_titles_below_threshold_do_not_collapse(self, make_paper):
        papers = [
            make_paper("Effects of fasting on insulin sensitivity"),
            make_paper("Mechanisms of coral bleaching in warming oceans"),
        ]
        assert len(deduplicate_by_recency(papers)) == 2

    def test_punctuation_and_case_do_not_defeat_dedup(self, make_paper):
        papers = [
            make_paper("Gut Microbiome & Lupus: A Review", year=2019),
            make_paper("gut microbiome and lupus a review", year=2020),
        ]
        assert len(deduplicate_by_recency(papers)) == 1

    def test_older_duplicate_does_not_replace_newer(self, make_paper):
        """Order must not matter — the newest wins whichever arrives first."""
        papers = [
            make_paper("Shared title here", paper_id="W1", year=2022),
            make_paper("Shared title here", paper_id="W2", year=2015),
        ]
        result = deduplicate_by_recency(papers)
        assert len(result) == 1
        assert result[0].year == 2022

    def test_equal_years_break_on_citation_count(self, make_paper):
        papers = [
            make_paper("Same year study", year=2020, citation_count=5, paper_id="W1"),
            make_paper("Same year study", year=2020, citation_count=99, paper_id="W2"),
        ]
        result = deduplicate_by_recency(papers)
        assert len(result) == 1
        assert result[0].citation_count == 99

    def test_missing_year_loses_to_a_dated_paper(self, make_paper):
        papers = [
            make_paper("Undated work", year=None, paper_id="W1"),
            make_paper("Undated work", year=2016, paper_id="W2"),
        ]
        result = deduplicate_by_recency(papers)
        assert len(result) == 1
        assert result[0].year == 2016

    def test_all_years_missing_keeps_exactly_one(self, make_paper):
        papers = [
            make_paper("Undated work", year=None, paper_id="W1"),
            make_paper("Undated work", year=None, paper_id="W2"),
        ]
        assert len(deduplicate_by_recency(papers)) == 1

    def test_empty_input(self):
        assert deduplicate_by_recency([]) == []

    def test_threshold_is_a_sane_ratio(self):
        assert 0.5 < TITLE_SIMILARITY_THRESHOLD <= 1.0


class TestPolicyAwareFiltering:
    def test_a_narrowed_policy_drops_out_of_field_papers(self, make_paper):
        policy = JournalPolicy.build(fields=["agriculture_food"])
        papers = [
            make_paper("Dairy work", journal_name="Journal of Dairy Science"),
            make_paper("Physics work", journal_name="Nature"),
        ]
        assert [p.title for p in filter_high_impact(papers, policy)] == ["Dairy work"]

    def test_extra_journals_are_honoured(self, make_paper):
        policy = JournalPolicy.build(fields=["medicine"], extra_journals=["Poultry Weekly"])
        papers = [make_paper("Bird study", journal_name="Poultry Weekly")]
        assert len(filter_high_impact(papers, policy)) == 1

    def test_the_default_argument_preserves_old_behaviour(self, make_paper):
        papers = [make_paper(journal_name="Nature"), make_paper(journal_name="Nowhere Journal")]
        assert len(filter_high_impact(papers)) == 1


class TestRejectedJournalCounts:
    def test_counts_excluded_journals_by_frequency(self, make_paper):
        papers = [
            make_paper(journal_name="Nowhere Journal"),
            make_paper(journal_name="Nowhere Journal"),
            make_paper(journal_name="Elsewhere Review"),
            make_paper(journal_name="Nature"),
        ]
        assert rejected_journal_counts(papers) == [
            {"journal": "Nowhere Journal", "count": 2},
            {"journal": "Elsewhere Review", "count": 1},
        ]

    def test_allowlisted_journals_are_never_reported(self, make_paper):
        papers = [make_paper(journal_name="Nature"), make_paper(journal_name="Cell")]
        assert rejected_journal_counts(papers) == []

    def test_papers_with_no_journal_are_skipped(self, make_paper):
        assert rejected_journal_counts([make_paper(journal_name=None)]) == []

    def test_respects_the_limit(self, make_paper):
        papers = [make_paper(journal_name=f"Journal {i}") for i in range(20)]
        assert len(rejected_journal_counts(papers, limit=5)) == 5

    def test_reflects_a_narrowed_policy(self, make_paper):
        """Under a narrow policy, otherwise-allowlisted journals show up here —
        which is exactly what tells the user their filter was too tight."""
        policy = JournalPolicy.build(fields=["agriculture_food"])
        papers = [make_paper(journal_name="Nature"), make_paper(journal_name="Cell")]
        reported = {entry["journal"] for entry in rejected_journal_counts(papers, policy)}
        assert reported == {"Nature", "Cell"}
