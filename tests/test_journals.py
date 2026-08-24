"""Tests for the high-impact journal policy (`app/journals.py`)."""

from __future__ import annotations

import pytest

from app.journals import (
    ALIASES,
    HIGH_IMPACT_JOURNALS,
    JOURNALS_BY_FIELD,
    is_high_impact,
    normalize_journal_name,
)


class TestNormalizeJournalName:
    def test_lowercases_and_strips(self):
        assert normalize_journal_name("  NATURE  ") == "nature"

    def test_collapses_internal_whitespace(self):
        assert normalize_journal_name("Nature   Communications") == "nature communications"

    def test_strips_edge_punctuation(self):
        assert normalize_journal_name("Nature.") == "nature"
        assert normalize_journal_name("- Science -") == "science"

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_blank_input_yields_empty_string(self, blank):
        assert normalize_journal_name(blank) == ""

    @pytest.mark.parametrize(
        ("raw", "canonical"),
        [
            ("PNAS", "proceedings of the national academy of sciences"),
            ("NEJM", "the new england journal of medicine"),
            ("Lancet", "the lancet"),
            ("JACS", "journal of the american chemical society"),
            ("Nat Commun", "nature communications"),
            ("BMJ", "the bmj"),
        ],
    )
    def test_resolves_aliases(self, raw, canonical):
        assert normalize_journal_name(raw) == canonical

    def test_every_alias_points_at_a_real_journal(self):
        """An alias mapping to a name not in the allowlist would silently never match."""
        for alias, canonical in ALIASES.items():
            assert canonical in HIGH_IMPACT_JOURNALS, f"alias {alias!r} -> unknown {canonical!r}"


class TestIsHighImpact:
    @pytest.mark.parametrize(
        "name",
        ["Nature", "science", "The Lancet", "Cell Metabolism", "PNAS", "nejm"],
    )
    def test_accepts_allowlisted_journals(self, name):
        assert is_high_impact(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "Journal of Unremarkable Findings",
            "International Journal of Predatory Publishing",
            "arXiv",
        ],
    )
    def test_rejects_unlisted_journals(self, name):
        assert is_high_impact(name) is False

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_rejects_blank(self, blank):
        assert is_high_impact(blank) is False

    def test_matching_is_case_and_punctuation_insensitive(self):
        assert is_high_impact("  tHe LaNcEt.  ") is True

    def test_allowlist_entries_are_normalized(self):
        """A non-normalized entry could never be matched — it would be dead weight."""
        for journal in HIGH_IMPACT_JOURNALS:
            assert journal == journal.lower().strip(), f"{journal!r} is not normalized"


class TestDisciplineCoverage:
    """Fields that the original ~38-journal allowlist could not serve.

    These began life as xfail(strict=True) markers documenting the gap. The
    field restructure closed it, so the markers came off.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "Journal of Dairy Science",
            "Poultry Science",
            "Journal of Animal Science",
            "Nature Food",
        ],
    )
    def test_agriculture_and_food_journals_are_accepted(self, name):
        assert is_high_impact(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "Journal of Machine Learning Research",
            "Nature Machine Intelligence",
            "Advances in Neural Information Processing Systems",
        ],
    )
    def test_computer_science_venues_are_accepted(self, name):
        assert is_high_impact(name) is True

    @pytest.mark.parametrize(
        "name", ["American Economic Review", "Econometrica", "Psychological Science"]
    )
    def test_social_science_journals_are_accepted(self, name):
        assert is_high_impact(name) is True

    def test_the_dairy_entry_is_the_full_title_not_a_fragment(self):
        """Regression: `"dairy science"` alone can never match, because
        matching is exact after normalization, not substring."""
        assert "journal of dairy science" in JOURNALS_BY_FIELD["agriculture_food"]
        assert is_high_impact("Dairy Science") is False
