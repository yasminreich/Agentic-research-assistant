"""Curated high-impact / reputable journal policy.

This module is the SINGLE place to edit which journals count as "high impact".
The Researcher Agent is instructed to target reputable venues, but the actual
allow/deny decision is made here, deterministically, so it is auditable and
reproducible.

Journals are grouped into **fields** so a caller can narrow the policy to the
disciplines a question actually concerns (see `JournalPolicy`). A caller may
also supply extra journal titles of its own — the web UI exposes both.

To broaden the policy permanently, add entries to `JOURNALS_BY_FIELD` (and to
`ALIASES` for common abbreviations). Names are matched case-insensitively after
normalization.

Two things to know when adding journals:

  - **Matching is exact after normalization, not substring.** `"dairy science"`
    will never match a paper published in the *Journal of Dairy Science*; the
    entry has to be the full title, `"journal of dairy science"`.
  - **Computer science largely publishes at conferences.** OpenAlex indexes
    those as venues too, so `cs_ai` lists proceedings names alongside journals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical, normalized journal names grouped by discipline. Keep every entry
# lowercase and complete — normalization lowercases incoming names before an
# exact match, so a fragment or a capitalized entry can never match anything.
JOURNALS_BY_FIELD: dict[str, set[str]] = {
    "multidisciplinary": {
        "nature",
        "science",
        "proceedings of the national academy of sciences",
        "nature communications",
        "science advances",
        "plos biology",
        "elife",
        "national science review",
    },
    "medicine": {
        "the lancet",
        "the new england journal of medicine",
        "jama",
        "the bmj",
        "nature medicine",
        "the lancet oncology",
        "the lancet neurology",
        "the lancet respiratory medicine",
        "annals of internal medicine",
        "circulation",
        "european heart journal",
        "journal of clinical oncology",
        "jama internal medicine",
        "jama cardiology",
        "gut",
        "diabetes care",
        "journal of the american college of cardiology",
        "blood",
        "hepatology",
        "science translational medicine",
    },
    "biology": {
        "cell",
        "cell metabolism",
        "molecular cell",
        "nature genetics",
        "nature biotechnology",
        "nature methods",
        "nature cell biology",
        "nature reviews molecular cell biology",
        "immunity",
        "nature immunology",
        "cancer cell",
        "cell stem cell",
        "developmental cell",
        "cell host & microbe",
        "genome biology",
        "the embo journal",
        "nucleic acids research",
        "plos genetics",
        "current biology",
        "nature microbiology",
        "microbiome",
    },
    "neuroscience": {
        "neuron",
        "nature neuroscience",
        "brain",
        "the journal of neuroscience",
        "nature reviews neuroscience",
        "trends in cognitive sciences",
        "annals of neurology",
        "molecular psychiatry",
        "biological psychiatry",
    },
    "chemistry": {
        "journal of the american chemical society",
        "nature chemistry",
        "angewandte chemie international edition",
        "chemical science",
        "chemical reviews",
        "chemical society reviews",
        "chem",
        "nature catalysis",
        "acs catalysis",
        "the journal of physical chemistry letters",
        "nature synthesis",
    },
    "physics": {
        "physical review letters",
        "nature physics",
        "physical review x",
        "reviews of modern physics",
        "nature photonics",
        "physical review b",
        "physical review d",
        "nature astronomy",
        "the astrophysical journal",
        "monthly notices of the royal astronomical society",
    },
    "materials_engineering": {
        "nature materials",
        "advanced materials",
        "nature nanotechnology",
        "nature energy",
        "acs nano",
        "joule",
        "energy & environmental science",
        "advanced functional materials",
        "advanced energy materials",
        "nature reviews materials",
        "matter",
        "nature electronics",
        "ieee transactions on robotics",
    },
    "cs_ai": {
        # Journals
        "journal of machine learning research",
        "nature machine intelligence",
        "ieee transactions on pattern analysis and machine intelligence",
        "communications of the acm",
        "acm transactions on graphics",
        "ieee transactions on information theory",
        "artificial intelligence",
        "transactions of the association for computational linguistics",
        "acm computing surveys",
        # Conference proceedings, which is where much of the field publishes.
        "advances in neural information processing systems",
        "international conference on machine learning",
        "international conference on learning representations",
        "proceedings of the aaai conference on artificial intelligence",
    },
    "earth_environment": {
        "nature climate change",
        "nature geoscience",
        "nature sustainability",
        "environmental science & technology",
        "global change biology",
        "earth system science data",
        "nature water",
        "reviews of geophysics",
        "atmospheric chemistry and physics",
        "the cryosphere",
    },
    "ecology_evolution": {
        "nature ecology & evolution",
        "ecology letters",
        "trends in ecology & evolution",
        "molecular biology and evolution",
        "ecology",
        "the american naturalist",
        "systematic biology",
        "journal of ecology",
    },
    "agriculture_food": {
        "journal of dairy science",
        "nature food",
        "poultry science",
        "journal of animal science",
        "food chemistry",
        "journal of agricultural and food chemistry",
        "animal",
        "the journal of nutrition",
        "the american journal of clinical nutrition",
        "advances in nutrition",
        "field crops research",
        "agricultural systems",
        "nature plants",
        "the plant cell",
        "journal of food science",
        "comprehensive reviews in food science and food safety",
    },
    "psychology": {
        "psychological science",
        "nature human behaviour",
        "journal of personality and social psychology",
        "psychological bulletin",
        "psychological review",
        "annual review of psychology",
        "behavioral and brain sciences",
        "perspectives on psychological science",
        "cognition",
    },
    "economics_social": {
        "american economic review",
        "the quarterly journal of economics",
        "econometrica",
        "journal of political economy",
        "the review of economic studies",
        "the economic journal",
        "the journal of finance",
        "american political science review",
        "american sociological review",
        "american journal of sociology",
        "management science",
    },
    "public_health": {
        "the lancet public health",
        "the lancet global health",
        "the lancet infectious diseases",
        "bulletin of the world health organization",
        "american journal of public health",
        "epidemiology",
        "international journal of epidemiology",
        "emerging infectious diseases",
    },
}

# Human-readable labels for the field keys above. The web UI renders these.
FIELD_LABELS: dict[str, str] = {
    "multidisciplinary": "Multidisciplinary",
    "medicine": "Medicine & clinical",
    "biology": "Biology & genetics",
    "neuroscience": "Neuroscience",
    "chemistry": "Chemistry",
    "physics": "Physics & astronomy",
    "materials_engineering": "Materials & engineering",
    "cs_ai": "Computer science & AI",
    "earth_environment": "Earth & environment",
    "ecology_evolution": "Ecology & evolution",
    "agriculture_food": "Agriculture & food science",
    "psychology": "Psychology & behaviour",
    "economics_social": "Economics & social science",
    "public_health": "Public health & epidemiology",
}

# Every journal, across every field. The default policy's backing set, and what
# callers that only need the flat allowlist should use.
HIGH_IMPACT_JOURNALS: set[str] = set().union(*JOURNALS_BY_FIELD.values())

# Common abbreviations / variants mapped to a canonical name in the sets above.
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
    # Agriculture / food / nutrition
    "j dairy sci": "journal of dairy science",
    "j anim sci": "journal of animal science",
    "ajcn": "the american journal of clinical nutrition",
    "american journal of clinical nutrition": "the american journal of clinical nutrition",
    "journal of nutrition": "the journal of nutrition",
    # Computer science
    "jmlr": "journal of machine learning research",
    "tpami": "ieee transactions on pattern analysis and machine intelligence",
    "neurips": "advances in neural information processing systems",
    "nips": "advances in neural information processing systems",
    "icml": "international conference on machine learning",
    "iclr": "international conference on learning representations",
    "cacm": "communications of the acm",
    # Economics
    "aer": "american economic review",
    "qje": "the quarterly journal of economics",
    "quarterly journal of economics": "the quarterly journal of economics",
    "jpe": "journal of political economy",
    "review of economic studies": "the review of economic studies",
    "journal of finance": "the journal of finance",
    # Leading-article variants OpenAlex sometimes reports without the article.
    "journal of neuroscience": "the journal of neuroscience",
    "embo journal": "the embo journal",
    "plant cell": "the plant cell",
    "economic journal": "the economic journal",
    "astrophysical journal": "the astrophysical journal",
}


def normalize_journal_name(name: str | None) -> str:
    """Lowercase, strip punctuation/whitespace, and resolve known aliases."""
    if not name:
        return ""
    cleaned = name.lower().strip()
    # Collapse internal whitespace and strip stray punctuation at the edges.
    # Leading-article differences ("Lancet" vs "The Lancet") are resolved via
    # ALIASES rather than by stripping, so the canonical set stays readable.
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .,:;-")
    return ALIASES.get(cleaned, cleaned)


class UnknownFieldError(ValueError):
    """Raised when a caller asks for a field key that does not exist."""


@dataclass(frozen=True)
class JournalPolicy:
    """Which journals a single research run will accept.

    Attributes:
        fields: Field keys to draw the allowlist from. `None` means every field.
        extra: Additional normalized journal names supplied by the caller, on
            top of whatever `fields` contributes.

    Build one via `JournalPolicy.build()`, which validates field keys and
    normalizes caller-supplied titles.
    """

    fields: frozenset[str] | None = None
    extra: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def build(
        cls,
        fields: list[str] | None = None,
        extra_journals: list[str] | None = None,
    ) -> JournalPolicy:
        """Validate and normalize the inputs into a policy.

        Args:
            fields: Field keys from `JOURNALS_BY_FIELD`. `None` (the field
                controls were never touched) means every field. An explicitly
                empty list means no field at all — the caller unchecked
                everything, so only `extra_journals` applies.
            extra_journals: Free-text journal titles, normalized the same way
                incoming paper journal names are so they match on equal terms.

        Raises:
            UnknownFieldError: if a field key is not in `JOURNALS_BY_FIELD`.
        """
        selected: frozenset[str] | None = None
        if fields is not None:
            unknown = sorted(set(fields) - set(JOURNALS_BY_FIELD))
            if unknown:
                raise UnknownFieldError(
                    f"Unknown field(s): {', '.join(unknown)}. "
                    f"Valid fields: {', '.join(sorted(JOURNALS_BY_FIELD))}."
                )
            selected = frozenset(fields)

        normalized_extra = frozenset(
            normalized
            for raw in (extra_journals or [])
            if (normalized := normalize_journal_name(raw))
        )
        return cls(fields=selected, extra=normalized_extra)

    @property
    def allowed(self) -> set[str]:
        """Every normalized journal name this policy accepts."""
        if self.fields is None:
            base = set(HIGH_IMPACT_JOURNALS)
        elif self.fields:
            base = set().union(*(JOURNALS_BY_FIELD[f] for f in self.fields))
        else:
            # Every field was explicitly unchecked; only `extra` applies.
            base = set()
        return base | set(self.extra)

    def allows(self, journal_name: str | None) -> bool:
        """Return True if `journal_name` is accepted under this policy."""
        normalized = normalize_journal_name(journal_name)
        return bool(normalized) and normalized in self.allowed

    def describe(self) -> str:
        """A short human-readable summary, used in the Researcher's prompt."""
        if self.fields is None:
            scope = "all fields"
        elif self.fields:
            scope = ", ".join(FIELD_LABELS.get(f, f) for f in sorted(self.fields))
        else:
            scope = "no field"
        if self.extra:
            scope += f", plus {len(self.extra)} journal(s) named by the user"
        return scope


DEFAULT_POLICY = JournalPolicy()


def is_high_impact(journal_name: str | None) -> bool:
    """Return True if `journal_name` is on the curated high-impact allowlist.

    Uses the default policy (every field). For a narrowed or extended policy,
    build a `JournalPolicy` and call `allows()` on it.
    """
    return DEFAULT_POLICY.allows(journal_name)
