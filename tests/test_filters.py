"""Tests for the deterministic post-processing steps (`app/filters.py`)."""

from __future__ import annotations

from app.filters import TITLE_SIMILARITY_THRESHOLD, deduplicate_by_recency, filter_high_impact


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
