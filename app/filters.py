"""Deterministic post-processing of search results.

Two reproducible steps applied to raw Paperclip results before they reach the
Researcher Agent:

1. `filter_high_impact` — keep only papers from journals the run's
   `JournalPolicy` allows.
2. `deduplicate_by_recency` — collapse near-duplicate papers (same work, or
   near-identical titles) and keep the most recent one.

The semantic notion of "papers that reach the same conclusion" is left to the
Researcher Agent; this module handles only the mechanical title-level dedup and
the recency rule.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from .journals import DEFAULT_POLICY, JournalPolicy
from .paperclip_client import Paper

# Two titles with a similarity ratio at/above this are treated as the same work.
TITLE_SIMILARITY_THRESHOLD = 0.92


def filter_high_impact(papers: list[Paper], policy: JournalPolicy = DEFAULT_POLICY) -> list[Paper]:
    """Keep only papers whose journal the policy allows.

    Defaults to `DEFAULT_POLICY` (every field), which is the behaviour callers
    had before policies existed.
    """
    return [p for p in papers if policy.allows(p.journal_name)]


def rejected_journal_counts(
    papers: list[Paper],
    policy: JournalPolicy = DEFAULT_POLICY,
    limit: int = 10,
) -> list[dict]:
    """The journals this policy filtered out, most frequent first.

    Surfaced to the caller so an empty result set can explain itself: the user
    sees which venues were dropped and can add the ones they trust rather than
    guessing why nothing came back.
    """
    counts = Counter(
        p.journal_name.strip()
        for p in papers
        if p.journal_name and not policy.allows(p.journal_name)
    )
    return [{"journal": name, "count": n} for name, n in counts.most_common(limit)]


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for comparison."""
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_more_recent(candidate: Paper, current: Paper) -> bool:
    """True if `candidate` should replace `current` as the kept paper.

    Prefer the more recent year; break ties on higher citation count.
    """
    cand_year = candidate.year or -1
    cur_year = current.year or -1
    if cand_year != cur_year:
        return cand_year > cur_year
    return candidate.citation_count > current.citation_count


def deduplicate_by_recency(papers: list[Paper]) -> list[Paper]:
    """Collapse near-duplicate papers, keeping the most recent of each group.

    Duplicates are detected by exact paper id, shared DOI, or near-identical
    normalized titles. Within a duplicate group the most recent year wins
    (ties broken by citation count).
    """
    kept: list[Paper] = []
    kept_norm_titles: list[str] = []
    seen_ids: dict[str, int] = {}  # paper_id / doi -> index in `kept`

    for paper in papers:
        norm_title = _normalize_title(paper.title)

        # Strong identity match: same paper id or DOI.
        match_index: int | None = None
        for key in (paper.paper_id, paper.doi):
            if key and key in seen_ids:
                match_index = seen_ids[key]
                break

        # Fuzzy title match against already-kept papers.
        if match_index is None:
            for idx, existing_title in enumerate(kept_norm_titles):
                if existing_title and norm_title:
                    ratio = SequenceMatcher(None, norm_title, existing_title).ratio()
                    if ratio >= TITLE_SIMILARITY_THRESHOLD:
                        match_index = idx
                        break

        if match_index is None:
            # New unique paper.
            index = len(kept)
            kept.append(paper)
            kept_norm_titles.append(norm_title)
            if paper.paper_id:
                seen_ids[paper.paper_id] = index
            if paper.doi:
                seen_ids[paper.doi] = index
            continue

        # Duplicate of an existing paper — keep whichever is more recent.
        if _is_more_recent(paper, kept[match_index]):
            kept[match_index] = paper
            kept_norm_titles[match_index] = norm_title
            if paper.paper_id:
                seen_ids[paper.paper_id] = match_index
            if paper.doi:
                seen_ids[paper.doi] = match_index

    return kept
