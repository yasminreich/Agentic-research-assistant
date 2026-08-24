"""Mechanical checks on what the Researcher Agent wrote.

The paper *list* in a report is already trustworthy: `tools.save_research_report`
resolves ids against papers the search actually returned, and `persistence`
writes titles, journals, years and DOIs from the API record. The model cannot
add a paper that does not exist.

The *prose* is not checked by any of that. The Researcher writes the summary and
cites papers inline by OpenAlex id, and until now nothing confirmed those ids
were real, or that a claim attributed to a paper appears anywhere in it.

This module closes that gap with two checks that are deliberately mechanical —
no model is asked to grade another model:

  `audit_citations`  every id cited in the prose is one the search returned
  `check_quotes`     every supporting quote appears in that paper's abstract

Both report *what they could not confirm* rather than asserting correctness. In
particular `no_abstract` is kept strictly separate from `not_found`: OpenAlex
has no abstract for many records, and calling those fabricated would be wrong
and would teach the reader to ignore the warnings.

What these checks still cannot tell you: whether a real quote from a real paper
actually supports the argument built on it. That is a reading, and it stays the
reader's job — which is why each paper is rendered with a resolvable DOI.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# OpenAlex work ids look like W2741809807. The id may appear bare or inside a
# full URL (https://openalex.org/W2741809807); both forms are matched, and the
# 6-digit floor avoids catching things like "W3" in ordinary prose.
CITATION_RE = re.compile(r"W\d{6,}")

# A quote at or above this similarity to some window of the abstract counts as
# present. Not 1.0 because models normalize quotes: they fix spacing, expand an
# abbreviation, or drop a bracketed aside. The same SequenceMatcher approach
# backs `filters.deduplicate_by_recency`.
QUOTE_SIMILARITY_THRESHOLD = 0.90

# Quotes shorter than this are too weak to verify — a handful of common words
# will fuzzy-match almost any abstract, so "supported" would mean nothing.
MIN_QUOTE_CHARS = 25

SUPPORTED = "supported"
NOT_FOUND = "not_found"
NO_ABSTRACT = "no_abstract"
TOO_SHORT = "too_short"


def bare_id(identifier: str) -> str:
    """Reduce an OpenAlex identifier to its bare work id.

    Papers are keyed by the full URL OpenAlex returns
    (`https://openalex.org/W4210744513`), but the Researcher cites the bare id
    in prose (`W4210744513`). Comparing the two forms directly matches nothing,
    which would report every citation as unverified. Both sides are reduced
    here before any comparison.
    """
    match = CITATION_RE.search(identifier or "")
    return match.group(0) if match else (identifier or "")


def extract_citations(summary: str) -> set[str]:
    """Every OpenAlex work id cited anywhere in the prose."""
    return set(CITATION_RE.findall(summary or ""))


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace/punctuation for comparison."""
    lowered = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", lowered).strip()


def quote_status(quote: str, abstract: str | None) -> str:
    """Whether `quote` appears in `abstract`.

    Returns one of `SUPPORTED`, `NOT_FOUND`, `NO_ABSTRACT`, `TOO_SHORT`.

    `NO_ABSTRACT` means "cannot check" and must never be presented as evidence
    of fabrication — OpenAlex simply has no abstract for many records.
    """
    normalized_quote = _normalize(quote)
    if len(normalized_quote) < MIN_QUOTE_CHARS:
        return TOO_SHORT
    if not abstract or not abstract.strip():
        return NO_ABSTRACT

    normalized_abstract = _normalize(abstract)
    if normalized_quote in normalized_abstract:
        return SUPPORTED

    # Slide a same-length window over the abstract and take the best match, so a
    # lightly reworded quote still counts while an invented one does not.
    span = len(normalized_quote)
    words = normalized_abstract.split(" ")
    best = 0.0
    for start in range(len(words)):
        window = " ".join(words[start:])[:span]
        if len(window) < span * 0.6:
            break
        best = max(best, SequenceMatcher(None, normalized_quote, window).ratio())
        if best >= QUOTE_SIMILARITY_THRESHOLD:
            return SUPPORTED
    return NOT_FOUND


def audit_citations(
    summary: str,
    selected_ids: list[str],
    retrieved_ids: set[str],
) -> dict:
    """Check the ids cited in the prose against the ids the search returned.

    Args:
        summary: The Researcher's prose.
        selected_ids: Papers listed as sources of the report.
        retrieved_ids: Every paper id any search in this run returned. An id
            outside this set was never seen by the run at all.

    Returns counts plus the ids behind each, so a caller can show specifics.
    """
    cited = extract_citations(summary)
    # Both sides reduced to the bare id: papers are keyed by full URL, prose
    # cites the short form.
    retrieved = {bare_id(i) for i in retrieved_ids}
    selected = {bare_id(i) for i in selected_ids}

    verified = sorted(cited & retrieved)
    unverified = sorted(cited - retrieved)
    # Listed as a source but never actually referred to in the prose. Not an
    # error — padding the reference list, at worst — so it is reported plainly.
    uncited = sorted(selected - cited)

    return {
        "cited_count": len(cited),
        "verified_count": len(verified),
        "verified": verified,
        "unverified": unverified,
        "uncited_selected": uncited,
    }


def check_quotes(evidence: list[dict], collected: dict[str, dict]) -> dict:
    """Check each supporting quote against the abstract of the paper it cites.

    Args:
        evidence: `[{"paper_id": "W...", "quote": "..."}]` as returned by the
            Researcher.
        collected: Full paper metadata by id, holding the complete abstract.
            Note the model only ever saw a truncated preview, so a genuine
            quote is always findable here.

    Returns per-quote results plus a tally by status.
    """
    results = []
    tally = {SUPPORTED: 0, NOT_FOUND: 0, NO_ABSTRACT: 0, TOO_SHORT: 0, "unknown_paper": 0}

    # Keyed by bare id so evidence can name a paper in either form.
    by_bare_id = {bare_id(key): value for key, value in collected.items()}

    for item in evidence or []:
        paper_id = (item or {}).get("paper_id", "")
        quote = (item or {}).get("quote", "")
        paper = by_bare_id.get(bare_id(paper_id))

        if paper is None:
            status = "unknown_paper"
        else:
            status = quote_status(quote, paper.get("abstract"))

        tally[status] = tally.get(status, 0) + 1
        results.append(
            {
                "paper_id": paper_id,
                "quote": quote,
                "status": status,
                "title": (paper or {}).get("title", ""),
            }
        )

    return {"results": results, "tally": tally, "total": len(results)}


def build_report(
    summary: str,
    selected_ids: list[str],
    retrieved_ids: set[str],
    evidence: list[dict],
    collected: dict[str, dict],
    unknown_paper_ids: list[str] | None = None,
) -> dict:
    """The full verification block attached to a run's result."""
    citations = audit_citations(summary, selected_ids, retrieved_ids)
    quotes = check_quotes(evidence, collected)
    return {
        "citations": citations,
        "quotes": quotes,
        # Ids the Researcher asked to include that no search had returned. These
        # were silently dropped from the paper list before this existed.
        "unknown_paper_ids": sorted(bare_id(i) for i in (unknown_paper_ids or [])),
        "ok": (
            not citations["unverified"]
            and not (unknown_paper_ids or [])
            and quotes["tally"].get(NOT_FOUND, 0) == 0
            and quotes["tally"].get("unknown_paper", 0) == 0
        ),
    }
