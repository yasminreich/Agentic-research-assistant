"""Tests for the citation and quote checks (`app/verification.py`).

The point of this module is to catch a model inventing a source or a finding, so
these tests spend most of their effort on inputs that SHOULD fail. A verifier
that has only ever been shown good input is not evidence of anything.
"""

from __future__ import annotations

import pytest

from app.verification import (
    NO_ABSTRACT,
    NOT_FOUND,
    SUPPORTED,
    TOO_SHORT,
    audit_citations,
    bare_id,
    build_report,
    check_quotes,
    extract_citations,
    quote_status,
)

ABSTRACT = (
    "Fasting improves insulin sensitivity in adults with obesity. We randomized "
    "120 participants to a time-restricted feeding protocol and observed "
    "significant reductions in fasting glucose over twelve weeks. Effects on "
    "body weight were modest and did not reach statistical significance."
)


class TestExtractCitations:
    def test_finds_bare_ids(self):
        assert extract_citations("Shown in (W2741809807).") == {"W2741809807"}

    def test_finds_ids_inside_urls(self):
        found = extract_citations("See https://openalex.org/W2741809807 for detail.")
        assert found == {"W2741809807"}

    def test_deduplicates_repeated_citations(self):
        assert extract_citations("(W123456) and again (W123456)") == {"W123456"}

    def test_finds_several(self):
        assert extract_citations("(W111111; W222222)") == {"W111111", "W222222"}

    def test_ignores_short_lookalikes(self):
        """ "W3" in ordinary prose is not a citation."""
        assert extract_citations("The W3 standard and W12 group") == set()

    @pytest.mark.parametrize("empty", ["", None])
    def test_handles_empty_input(self, empty):
        assert extract_citations(empty) == set()


class TestQuoteStatus:
    def test_an_exact_quote_is_supported(self):
        quote = "We randomized 120 participants to a time-restricted feeding protocol"
        assert quote_status(quote, ABSTRACT) == SUPPORTED

    def test_case_and_spacing_do_not_matter(self):
        quote = "WE  RANDOMIZED   120 PARTICIPANTS to a time-restricted feeding protocol"
        assert quote_status(quote, ABSTRACT) == SUPPORTED

    def test_light_rewording_still_counts(self):
        """Models normalise quotes — British spelling, hyphens, punctuation."""
        quote = "we randomised 120 participants to a time restricted feeding protocol"
        assert quote_status(quote, ABSTRACT) == SUPPORTED

    def test_an_invented_quote_is_not_found(self):
        quote = "Fasting cured every participant of type 2 diabetes within three days"
        assert quote_status(quote, ABSTRACT) == NOT_FOUND

    def test_a_reversed_claim_is_not_found(self):
        """The dangerous case: plausible, on-topic, and says the opposite."""
        quote = "Effects on body weight were large and highly statistically significant"
        assert quote_status(quote, ABSTRACT) == NOT_FOUND

    def test_a_quote_from_a_different_paper_is_not_found(self):
        quote = "The gut microbiome regulates host immune development through SCFAs"
        assert quote_status(quote, ABSTRACT) == NOT_FOUND

    @pytest.mark.parametrize("missing", [None, "", "   "])
    def test_a_missing_abstract_is_uncheckable_not_fabricated(self, missing):
        """This distinction matters: OpenAlex has no abstract for many records,
        and reporting those as invented would train the reader to ignore the
        warnings entirely."""
        quote = "We randomized 120 participants to a time-restricted feeding protocol"
        assert quote_status(quote, missing) == NO_ABSTRACT

    def test_a_trivially_short_quote_is_rejected(self):
        """A few common words fuzzy-match almost anything, so "supported" would
        be meaningless."""
        assert quote_status("Fasting works", ABSTRACT) == TOO_SHORT

    def test_a_short_quote_is_rejected_even_when_present(self):
        assert quote_status("Fasting improves", ABSTRACT) == TOO_SHORT


class TestAuditCitations:
    def test_all_citations_real(self):
        result = audit_citations("Shown in (W111111) and (W222222).", [], {"W111111", "W222222"})
        assert result["cited_count"] == 2
        assert result["verified_count"] == 2
        assert result["unverified"] == []

    def test_an_invented_citation_is_flagged(self):
        result = audit_citations("Shown in (W999999).", [], {"W111111"})
        assert result["unverified"] == ["W999999"]
        assert result["verified_count"] == 0

    def test_partially_invented(self):
        result = audit_citations("(W111111) and (W999999)", [], {"W111111"})
        assert result["verified"] == ["W111111"]
        assert result["unverified"] == ["W999999"]

    def test_a_selected_paper_never_cited_is_reported(self):
        result = audit_citations("Only (W111111) matters.", ["W111111", "W222222"], {"W111111"})
        assert result["uncited_selected"] == ["W222222"]

    def test_a_summary_with_no_citations(self):
        result = audit_citations("No sources named at all.", ["W111111"], {"W111111"})
        assert result["cited_count"] == 0
        assert result["uncited_selected"] == ["W111111"]


class TestCheckQuotes:
    @staticmethod
    def collected(abstract=ABSTRACT):
        return {"W111111": {"abstract": abstract, "title": "A fasting trial"}}

    def test_a_good_quote_tallies_as_supported(self):
        evidence = [
            {
                "paper_id": "W111111",
                "quote": "We randomized 120 participants to a time-restricted feeding protocol",
            }
        ]
        report = check_quotes(evidence, self.collected())
        assert report["tally"][SUPPORTED] == 1
        assert report["results"][0]["title"] == "A fasting trial"

    def test_an_invented_quote_tallies_as_not_found(self):
        evidence = [{"paper_id": "W111111", "quote": "Fasting cured all participants outright"}]
        assert check_quotes(evidence, self.collected())["tally"][NOT_FOUND] == 1

    def test_a_quote_against_an_unknown_paper(self):
        evidence = [{"paper_id": "W999999", "quote": "x" * 40}]
        report = check_quotes(evidence, self.collected())
        assert report["tally"]["unknown_paper"] == 1

    def test_a_paper_without_an_abstract(self):
        evidence = [
            {
                "paper_id": "W111111",
                "quote": "We randomized 120 participants to a time-restricted feeding protocol",
            }
        ]
        report = check_quotes(evidence, self.collected(abstract=None))
        assert report["tally"][NO_ABSTRACT] == 1

    @pytest.mark.parametrize("empty", [None, []])
    def test_no_evidence_at_all(self, empty):
        report = check_quotes(empty, self.collected())
        assert report["total"] == 0
        assert report["results"] == []

    def test_malformed_entries_do_not_crash(self):
        """The model can return junk; that must not take down a finished run."""
        report = check_quotes([{}, {"paper_id": "W111111"}, None], self.collected())
        assert report["total"] == 3


class TestBuildReport:
    COLLECTED = {"W111111": {"abstract": ABSTRACT, "title": "A fasting trial"}}
    GOOD_QUOTE = "We randomized 120 participants to a time-restricted feeding protocol"

    def test_a_clean_report_is_ok(self):
        report = build_report(
            summary="Fasting helps (W111111).",
            selected_ids=["W111111"],
            retrieved_ids={"W111111"},
            evidence=[{"paper_id": "W111111", "quote": self.GOOD_QUOTE}],
            collected=self.COLLECTED,
        )
        assert report["ok"] is True

    def test_an_invented_citation_makes_it_not_ok(self):
        report = build_report(
            summary="Fasting helps (W999999).",
            selected_ids=["W111111"],
            retrieved_ids={"W111111"},
            evidence=[],
            collected=self.COLLECTED,
        )
        assert report["ok"] is False
        assert report["citations"]["unverified"] == ["W999999"]

    def test_an_invented_quote_makes_it_not_ok(self):
        report = build_report(
            summary="Fasting helps (W111111).",
            selected_ids=["W111111"],
            retrieved_ids={"W111111"},
            evidence=[{"paper_id": "W111111", "quote": "Fasting cured all participants outright"}],
            collected=self.COLLECTED,
        )
        assert report["ok"] is False

    def test_a_missing_abstract_alone_does_not_make_it_not_ok(self):
        """Uncheckable is not the same as wrong, and must not be reported as
        though the model did something."""
        report = build_report(
            summary="Fasting helps (W111111).",
            selected_ids=["W111111"],
            retrieved_ids={"W111111"},
            evidence=[{"paper_id": "W111111", "quote": self.GOOD_QUOTE}],
            collected={"W111111": {"abstract": None, "title": "A fasting trial"}},
        )
        assert report["quotes"]["tally"][NO_ABSTRACT] == 1
        assert report["ok"] is True

    def test_dropped_paper_ids_are_surfaced(self):
        """These used to vanish into a log line the user never saw."""
        report = build_report(
            summary="Fasting helps (W111111).",
            selected_ids=["W111111"],
            retrieved_ids={"W111111"},
            evidence=[],
            collected=self.COLLECTED,
            unknown_paper_ids=["W888888"],
        )
        assert report["unknown_paper_ids"] == ["W888888"]
        assert report["ok"] is False


class TestIdFormNormalization:
    """OpenAlex keys papers by full URL; the model cites the bare id.

    Comparing the two forms directly matches nothing, which would report every
    citation in every run as unverified — a false alarm loud enough to make the
    whole feature worthless. Both sides are reduced before comparison.
    """

    URL = "https://openalex.org/W4210744513"
    BARE = "W4210744513"

    def test_bare_id_extracts_from_a_url(self):
        assert bare_id(self.URL) == self.BARE

    def test_bare_id_passes_a_bare_id_through(self):
        assert bare_id(self.BARE) == self.BARE

    @pytest.mark.parametrize("junk", ["", None, "not-an-id"])
    def test_bare_id_survives_junk(self, junk):
        assert bare_id(junk) == (junk or "")

    def test_a_prose_citation_matches_a_url_keyed_paper(self):
        result = audit_citations(f"Shown in ({self.BARE}).", [self.URL], {self.URL})
        assert result["verified"] == [self.BARE]
        assert result["unverified"] == []
        assert result["uncited_selected"] == []

    def test_evidence_naming_a_bare_id_finds_a_url_keyed_paper(self):
        collected = {self.URL: {"abstract": ABSTRACT, "title": "A fasting trial"}}
        quote = "We randomized 120 participants to a time-restricted feeding protocol"
        report = check_quotes([{"paper_id": self.BARE, "quote": quote}], collected)
        assert report["tally"][SUPPORTED] == 1

    def test_dropped_ids_are_reported_in_bare_form(self):
        report = build_report(
            summary="Summary.",
            selected_ids=[],
            retrieved_ids=set(),
            evidence=[],
            collected={},
            unknown_paper_ids=["https://openalex.org/W8888888"],
        )
        assert report["unknown_paper_ids"] == ["W8888888"]
