"""Curated high-impact / reputable journal policy.

This module is the SINGLE place to edit which journals count as "high impact".
The Researcher Agent is instructed to target reputable venues, but the actual
allow/deny decision is made here, deterministically, so it is auditable and
reproducible.

To broaden or narrow the policy, edit `HIGH_IMPACT_JOURNALS` (and `ALIASES` for
common abbreviations). Names are matched case-insensitively after normalization.
"""

from __future__ import annotations

import re

# Canonical, normalized journal names considered high-impact / reputable.
# Keep these lowercase; normalization lowercases incoming names before matching.
HIGH_IMPACT_JOURNALS: set[str] = {
    # Multidisciplinary
    "nature",
    "science",
    "proceedings of the national academy of sciences",
    "nature communications",
    "science advances",
    "plos biology",
    "elife",
    # Medicine / clinical
    "the lancet",
    "the new england journal of medicine",
    "jama",
    "the bmj",
    "nature medicine",
    "the lancet oncology",
    "annals of internal medicine",
    "circulation",
    "journal of clinical oncology",
    "the lancet neurology",
    # Cell / molecular biology
    "cell",
    "cell metabolism",
    "molecular cell",
    "nature genetics",
    "nature biotechnology",
    "nature methods",
    "nature cell biology",
    "immunity",
    "cancer cell",
    # Neuroscience
    "neuron",
    "nature neuroscience",
    # Chemistry / physics / materials
    "journal of the american chemical society",
    "nature chemistry",
    "nature physics",
    "nature materials",
    "physical review letters",
    "angewandte chemie international edition",
    "advanced materials",
    # Earth / environment
    "nature climate change",
    "nature geoscience",
}

# Common abbreviations / variants mapped to a canonical name in the set above.
ALIASES: dict[str, str] = {
    "pnas": "proceedings of the national academy of sciences",
    "proc natl acad sci": "proceedings of the national academy of sciences",
    "nejm": "the new england journal of medicine",
    "new england journal of medicine": "the new england journal of medicine",
    "n engl j med": "the new england journal of medicine",
    "lancet": "the lancet",
    "bmj": "the bmj",
    "british medical journal": "the bmj",
    "jacs": "journal of the american chemical society",
    "j am chem soc": "journal of the american chemical society",
    "nat commun": "nature communications",
    "nature commun": "nature communications",
    "prl": "physical review letters",
    "angew chem int ed": "angewandte chemie international edition",
    "jama : the journal of the american medical association": "jama",
}


def normalize_journal_name(name: str | None) -> str:
    """Lowercase, strip punctuation/whitespace, and resolve known aliases."""
    if not name:
        return ""
    cleaned = name.lower().strip()
    # Drop a leading article inconsistency is handled via the canonical set
    # (e.g. "the lancet"). Collapse internal whitespace and strip stray
    # punctuation at the edges.
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .,:;-")
    return ALIASES.get(cleaned, cleaned)


def is_high_impact(journal_name: str | None) -> bool:
    """Return True if `journal_name` is on the curated high-impact allowlist."""
    return normalize_journal_name(journal_name) in HIGH_IMPACT_JOURNALS
