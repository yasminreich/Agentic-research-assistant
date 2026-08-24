"""Tests for per-run journal selection (`app.journals.JournalPolicy`)."""

from __future__ import annotations

import dataclasses

import pytest

from app.journals import (
    DEFAULT_POLICY,
    FIELD_LABELS,
    HIGH_IMPACT_JOURNALS,
    JOURNALS_BY_FIELD,
    JournalPolicy,
    UnknownFieldError,
)


class TestFieldTable:
    def test_every_field_has_a_label(self):
        assert set(JOURNALS_BY_FIELD) == set(FIELD_LABELS)

    def test_no_field_is_empty(self):
        for key, journals in JOURNALS_BY_FIELD.items():
            assert journals, f"field {key!r} has no journals"

    def test_the_flat_allowlist_is_the_union_of_the_fields(self):
        union = set().union(*JOURNALS_BY_FIELD.values())
        assert HIGH_IMPACT_JOURNALS == union

    def test_every_entry_is_normalized(self):
        """A capitalized or padded entry could never match — matching is exact
        after normalization."""
        for key, journals in JOURNALS_BY_FIELD.items():
            for journal in journals:
                assert journal == journal.lower().strip(), f"{journal!r} in {key!r}"


class TestDefaultPolicy:
    def test_accepts_every_field(self):
        for journals in JOURNALS_BY_FIELD.values():
            for journal in journals:
                assert DEFAULT_POLICY.allows(journal)

    def test_rejects_anything_unlisted(self):
        assert DEFAULT_POLICY.allows("Journal of Unremarkable Findings") is False

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_rejects_blank(self, blank):
        assert DEFAULT_POLICY.allows(blank) is False

    def test_build_with_no_arguments_matches_the_default(self):
        assert JournalPolicy.build().allowed == DEFAULT_POLICY.allowed


class TestFieldSelection:
    def test_narrows_to_the_chosen_field(self):
        policy = JournalPolicy.build(fields=["agriculture_food"])
        assert policy.allows("Journal of Dairy Science") is True
        assert policy.allows("Nature") is False

    def test_several_fields_union_together(self):
        policy = JournalPolicy.build(fields=["agriculture_food", "multidisciplinary"])
        assert policy.allows("Journal of Dairy Science") is True
        assert policy.allows("Nature") is True
        assert policy.allows("American Economic Review") is False

    @pytest.mark.parametrize("empty", [None, []])
    def test_no_selection_means_every_field(self, empty):
        assert JournalPolicy.build(fields=empty).allowed == HIGH_IMPACT_JOURNALS

    def test_an_unknown_field_is_rejected_with_a_helpful_message(self):
        with pytest.raises(UnknownFieldError) as exc:
            JournalPolicy.build(fields=["astrology"])
        assert "astrology" in str(exc.value)
        assert "agriculture_food" in str(exc.value), "the error should list valid fields"

    def test_unknown_field_error_is_a_value_error(self):
        """The server maps ValueError to 422, so this must stay a subclass."""
        assert issubclass(UnknownFieldError, ValueError)

    def test_duplicate_field_keys_are_harmless(self):
        policy = JournalPolicy.build(fields=["medicine", "medicine"])
        assert policy.allows("The Lancet") is True


class TestExtraJournals:
    def test_a_user_supplied_journal_is_accepted(self):
        policy = JournalPolicy.build(fields=["agriculture_food"], extra_journals=["Poultry Weekly"])
        assert policy.allows("Poultry Weekly") is True

    def test_extras_are_normalized_like_incoming_names(self):
        policy = JournalPolicy.build(extra_journals=["  JOURNAL of Odd Results.  "])
        assert policy.allows("journal of odd results") is True

    def test_extras_resolve_aliases_too(self):
        policy = JournalPolicy.build(fields=["medicine"], extra_journals=["JMLR"])
        assert policy.allows("Journal of Machine Learning Research") is True

    @pytest.mark.parametrize("junk", ["", "   ", "..."])
    def test_blank_extras_are_dropped(self, junk):
        policy = JournalPolicy.build(fields=["medicine"], extra_journals=[junk])
        assert policy.extra == frozenset()

    def test_extras_add_to_rather_than_replace_the_fields(self):
        policy = JournalPolicy.build(fields=["medicine"], extra_journals=["Poultry Weekly"])
        assert policy.allows("The Lancet") is True
        assert policy.allows("Poultry Weekly") is True

    def test_extras_alone_narrow_to_just_those(self):
        """With no fields chosen the default is still every field; extras add on
        top rather than switching to an extras-only list."""
        policy = JournalPolicy.build(extra_journals=["Poultry Weekly"])
        assert policy.allows("Nature") is True
        assert policy.allows("Poultry Weekly") is True


class TestDescribe:
    def test_the_default_says_all_fields(self):
        assert DEFAULT_POLICY.describe() == "all fields"

    def test_named_fields_use_human_labels(self):
        assert JournalPolicy.build(fields=["agriculture_food"]).describe() == (
            "Agriculture & food science"
        )

    def test_several_fields_are_listed(self):
        described = JournalPolicy.build(fields=["medicine", "chemistry"]).describe()
        assert "Medicine & clinical" in described
        assert "Chemistry" in described

    def test_extras_are_counted_not_listed(self):
        described = JournalPolicy.build(
            fields=["medicine"], extra_journals=["Poultry Weekly", "Duck Quarterly"]
        ).describe()
        assert "2 journal(s) named by the user" in described


class TestImmutability:
    def test_a_policy_is_hashable_and_frozen(self):
        policy = JournalPolicy.build(fields=["medicine"])
        assert hash(policy)
        with pytest.raises(dataclasses.FrozenInstanceError):
            policy.fields = frozenset({"chemistry"})

    def test_allowed_does_not_mutate_the_module_allowlist(self):
        before = set(HIGH_IMPACT_JOURNALS)
        JournalPolicy.build(extra_journals=["Poultry Weekly"]).allowed.add("scratch")
        assert HIGH_IMPACT_JOURNALS == before
