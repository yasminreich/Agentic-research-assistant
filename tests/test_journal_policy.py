"""Tests for per-run journal selection (`app.journals.JournalPolicy`)."""

from __future__ import annotations

import dataclasses

import pytest

from app.journals import (
    DEFAULT_POLICY,
    FIELD_ALIASES,
    FIELD_GROUPS,
    FIELD_LABELS,
    HIGH_IMPACT_JOURNALS,
    JOURNALS_BY_FIELD,
    JournalPolicy,
    UnknownFieldError,
    is_high_impact,
    normalize_journal_name,
    resolve_fields,
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

    def test_untouched_controls_mean_every_field(self):
        """`None` = the caller never touched the field controls."""
        assert JournalPolicy.build(fields=None).allowed == HIGH_IMPACT_JOURNALS

    def test_an_explicitly_empty_list_means_no_field(self):
        """`[]` = the user unchecked everything, which is a real choice and must
        not silently widen back to "search everything"."""
        assert JournalPolicy.build(fields=[]).allowed == set()

    def test_an_empty_list_plus_extras_searches_only_the_extras(self):
        policy = JournalPolicy.build(fields=[], extra_journals=["Poultry Weekly"])
        assert policy.allows("Poultry Weekly") is True
        assert policy.allows("Nature") is False

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

    def test_extras_without_touching_the_fields_add_to_all_of_them(self):
        """Naming a journal should not silently narrow the default scope."""
        policy = JournalPolicy.build(extra_journals=["Poultry Weekly"])
        assert policy.allows("Nature") is True
        assert policy.allows("Poultry Weekly") is True


class TestDescribe:
    def test_the_default_says_all_fields(self):
        assert DEFAULT_POLICY.describe() == "all fields"

    def test_an_empty_selection_says_no_field(self):
        assert (
            JournalPolicy.build(fields=[], extra_journals=["X"]).describe().startswith("no field")
        )

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


class TestFieldGroups:
    def test_every_field_appears_in_exactly_one_group(self):
        grouped = [key for keys in FIELD_GROUPS.values() for key in keys]
        assert sorted(grouped) == sorted(JOURNALS_BY_FIELD)
        assert len(grouped) == len(set(grouped)), "a field is in two groups"

    def test_no_group_is_empty(self):
        for name, keys in FIELD_GROUPS.items():
            assert keys, f"group {name!r} has no fields"


class TestRetiredFieldKeys:
    def test_cs_ai_still_resolves_after_the_split(self):
        """A saved UI selection or an older API caller must not start erroring."""
        policy = JournalPolicy.build(fields=["cs_ai"])
        assert policy.fields == frozenset({"ai_ml", "computer_science"})
        assert policy.allows("Journal of Machine Learning Research") is True
        assert policy.allows("Communications of the ACM") is True

    def test_resolve_fields_preserves_order_and_deduplicates(self):
        assert resolve_fields(["medicine", "cs_ai", "ai_ml"]) == [
            "medicine",
            "ai_ml",
            "computer_science",
        ]

    def test_every_alias_target_is_a_real_field(self):
        for retired, replacements in FIELD_ALIASES.items():
            for key in replacements:
                assert key in JOURNALS_BY_FIELD, f"{retired} -> unknown {key}"


class TestNormalizationOfPeriods:
    @pytest.mark.parametrize(
        ("reported", "expected"),
        [
            # OpenAlex spells the Nature Reviews family with an internal period.
            ("Nature reviews. Immunology", "nature reviews immunology"),
            ("Nature Reviews Immunology", "nature reviews immunology"),
            ("Nature reviews. Microbiology", "nature reviews microbiology"),
            # Abbreviated forms collapse onto their alias.
            ("J. Dairy Sci.", "journal of dairy science"),
        ],
    )
    def test_internal_periods_are_separators(self, reported, expected):
        assert normalize_journal_name(reported) == expected

    @pytest.mark.parametrize(
        "reported",
        ["Nature reviews. Immunology", "Nature Reviews Immunology", "J. Dairy Sci."],
    )
    def test_both_spellings_are_accepted(self, reported):
        assert is_high_impact(reported) is True


class TestNewDisciplines:
    @pytest.mark.parametrize(
        ("field", "journal"),
        [
            ("microbiome", "The ISME Journal"),
            ("microbiome", "Gut Microbes"),
            ("immunology", "Science Immunology"),
            ("immunology", "Cellular and Molecular Immunology"),
            ("bioinformatics", "Genome Research"),
            ("ai_ml", "Journal of Machine Learning Research"),
            ("computer_science", "Communications of the ACM"),
            ("security_privacy", "USENIX Security Symposium"),
            ("statistics_data_science", "Biometrika"),
            ("robotics", "Science Robotics"),
            ("hci", "ACM Transactions on Computer-Human Interaction"),
            ("education", "Review of Educational Research"),
            ("law_policy", "Harvard Law Review"),
        ],
    )
    def test_the_field_accepts_its_journal(self, field, journal):
        assert JournalPolicy.build(fields=[field]).allows(journal) is True

    def test_mega_journals_stay_excluded(self):
        """Frontiers/Nutrients/IJMS are peer-reviewed but not selective. Keeping
        them out is the point of the filter; users can add them per run."""
        for name in ["Frontiers in Immunology", "Nutrients", "Scientific Reports"]:
            assert is_high_impact(name) is False
