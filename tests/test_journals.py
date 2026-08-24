"""Tests for the high-impact journal policy (`app/journals.py`)."""

from __future__ import annotations

import pytest

from app.journals import ALIASES, HIGH_IMPACT_JOURNALS, is_high_impact, normalize_journal_name


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


class TestCoverageGaps:
    """Fields the current allowlist cannot serve.

    These are `xfail(strict=True)` rather than deleted: they document a real
    limitation and will fail loudly the moment it is fixed, which is the signal
    to drop the marker.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="Allowlist is ~38 mostly biomedical journals; agriculture is not covered yet.",
    )
    def test_journal_of_dairy_science_is_accepted(self):
        assert is_high_impact("Journal of Dairy Science") is True

    @pytest.mark.xfail(
        strict=True,
        reason="Computer science and economics venues are not covered yet.",
    )
    @pytest.mark.parametrize(
        "name", ["Journal of Machine Learning Research", "American Economic Review"]
    )
    def test_other_disciplines_are_accepted(self, name):
        assert is_high_impact(name) is True
