"""Curated high-impact / reputable journal policy.

This module is the SINGLE place to edit which journals count as "high impact".
The Researcher Agent is instructed to target reputable venues, but the actual
allow/deny decision is made here, deterministically, so it is auditable and
reproducible.

Journals are grouped into **fields** so a caller can narrow the policy to the
disciplines a question actually concerns (see `JournalPolicy`), and fields are
grouped again into `FIELD_GROUPS` purely so the web UI can render them in
readable sections. A caller may also supply extra journal titles of its own.

To broaden the policy permanently, add entries to `JOURNALS_BY_FIELD` (and to
`ALIASES` for abbreviations), then run `python -m scripts.validate_journals` to
confirm OpenAlex actually reports the names you added.

Four things to know when adding journals:

  - **Matching is exact after normalization, not substring.** `"dairy science"`
    will never match a paper published in the *Journal of Dairy Science*; the
    entry has to be the full title, `"journal of dairy science"`.
  - **Use the title OpenAlex reports, which is not always the obvious one.**
    It says *The ISME Journal*, *Cellular and Molecular Immunology* (not `&`),
    and *The Journal of Experimental Medicine*. When in doubt, check.
  - **Some venues are year-stamped and cannot be listed.** OpenAlex indexes CVPR
    as `2022 IEEE/CVF Conference on Computer Vision and Pattern Recognition
    (CVPR)` and ACM CCS as `Proceedings of the 2022 ACM SIGSAC Conference on...`.
    A fixed allowlist entry can never match those, so they are deliberately
    absent rather than added as dead weight.
  - **Mega-journals are deliberately excluded.** *Frontiers in ...*, *Nutrients*,
    *IJMS*, *Scientific Reports* and similar are peer-reviewed but not selective,
    and adding them would defeat the point of the filter. They appear in the
    per-run "excluded journals" list, so anyone who wants them can add them by
    name for that run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical, normalized journal names grouped by discipline. Keep every entry
# lowercase and complete — normalization lowercases incoming names before an
# exact match, so a fragment or a capitalized entry can never match anything.
JOURNALS_BY_FIELD: dict[str, set[str]] = {
    # --- General ----------------------------------------------------------
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
    # --- Life sciences ----------------------------------------------------
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
        "ebiomedicine",
        "cell reports medicine",
        "plos medicine",
        "nature reviews drug discovery",
        "nature reviews cancer",
        "nature reviews clinical oncology",
        "nature reviews cardiology",
        "nature reviews gastroenterology & hepatology",
        "nature reviews nephrology",
        "nature reviews endocrinology",
        "signal transduction and targeted therapy",
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
        "nature reviews genetics",
        "cancer cell",
        "cell stem cell",
        "developmental cell",
        "cell reports",
        "cell research",
        "genome biology",
        "the embo journal",
        "nucleic acids research",
        "plos genetics",
        "current biology",
        "nature aging",
        "nature metabolism",
        "physiological reviews",
        "science signaling",
        "trends in cell biology",
        "annual review of physiology",
    },
    "microbiome": {
        # Names verified against what OpenAlex itself reports.
        "the isme journal",
        "gut microbes",
        "microbiome",
        "msystems",
        "mbio",
        "trends in microbiology",
        "nature microbiology",
        "nature reviews microbiology",
        "microbiology and molecular biology reviews",
        "cell host & microbe",
        "npj biofilms and microbiomes",
        "applied and environmental microbiology",
    },
    "immunology": {
        "immunity",
        "nature immunology",
        "science immunology",
        "nature reviews immunology",
        "mucosal immunology",
        "cellular and molecular immunology",
        "annual review of immunology",
        "the journal of experimental medicine",
        "trends in immunology",
        "the journal of immunology",
        "journal of neuroinflammation",
    },
    "bioinformatics": {
        "bioinformatics",
        "genome research",
        "plos computational biology",
        "briefings in bioinformatics",
        "nature computational science",
        "bmc bioinformatics",
        "nature methods",
        "genome biology",
    },
    "neuroscience": {
        "neuron",
        "nature neuroscience",
        "brain",
        "the journal of neuroscience",
        "nature reviews neuroscience",
        "nature reviews neurology",
        "trends in cognitive sciences",
        "annals of neurology",
        "molecular psychiatry",
        "biological psychiatry",
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
    # --- Physical sciences ------------------------------------------------
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
    # --- Computing --------------------------------------------------------
    # Conference proceedings are where much of computing publishes. OpenAlex
    # indexes some under a fixed name (usable here) and others under a
    # year-stamped one (not usable). Only the fixed ones are listed.
    "ai_ml": {
        "journal of machine learning research",
        "nature machine intelligence",
        "ieee transactions on pattern analysis and machine intelligence",
        "transactions of the association for computational linguistics",
        "artificial intelligence",
        "neural information processing systems",
        "international conference on machine learning",
        "international conference on learning representations",
        "proceedings of the aaai conference on artificial intelligence",
        "journal of artificial intelligence research",
    },
    "computer_science": {
        "communications of the acm",
        "acm computing surveys",
        "acm transactions on graphics",
        "ieee transactions on information theory",
        "proceedings of the acm on programming languages",
        "acm transactions on software engineering and methodology",
        "ieee transactions on software engineering",
        "journal of the acm",
        "siam journal on computing",
        "ieee transactions on parallel and distributed systems",
    },
    "security_privacy": {
        "usenix security symposium",
        "network and distributed system security symposium",
        "ieee transactions on information forensics and security",
        "ieee transactions on dependable and secure computing",
        "journal of cryptology",
        "proceedings on privacy enhancing technologies",
        "computers & security",
        "acm transactions on privacy and security",
    },
    "statistics_data_science": {
        "the annals of statistics",
        "journal of the american statistical association",
        "journal of the royal statistical society series b (statistical methodology)",
        "biometrika",
        "statistical science",
        "the annals of applied statistics",
        "journal of statistical software",
        "biostatistics",
    },
    "robotics": {
        "ieee transactions on robotics",
        "science robotics",
        "the international journal of robotics research",
        "ieee robotics and automation letters",
        "autonomous robots",
    },
    "hci": {
        "acm transactions on computer-human interaction",
        "proceedings of the acm on human-computer interaction",
        "international journal of human-computer studies",
        "human-computer interaction",
    },
    # --- Social sciences --------------------------------------------------
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
    "education": {
        "review of educational research",
        "journal of the learning sciences",
        "educational researcher",
        "computers & education",
        "american educational research journal",
        "learning and instruction",
    },
    "law_policy": {
        "harvard law review",
        "the yale law journal",
        "columbia law review",
        "stanford law review",
        "the journal of legal studies",
        "law & society review",
    },
}

# Human-readable labels for the field keys above. The web UI renders these.
FIELD_LABELS: dict[str, str] = {
    "multidisciplinary": "Multidisciplinary",
    "medicine": "Medicine & clinical",
    "biology": "Biology & genetics",
    "microbiome": "Microbiome & microbiology",
    "immunology": "Immunology",
    "bioinformatics": "Bioinformatics & comp. biology",
    "neuroscience": "Neuroscience",
    "public_health": "Public health & epidemiology",
    "agriculture_food": "Agriculture & food science",
    "ecology_evolution": "Ecology & evolution",
    "chemistry": "Chemistry",
    "physics": "Physics & astronomy",
    "materials_engineering": "Materials & engineering",
    "earth_environment": "Earth & environment",
    "ai_ml": "AI & machine learning",
    "computer_science": "Computer science",
    "security_privacy": "Security & privacy",
    "statistics_data_science": "Statistics & data science",
    "robotics": "Robotics",
    "hci": "Human-computer interaction",
    "psychology": "Psychology & behaviour",
    "economics_social": "Economics & social science",
    "education": "Education",
    "law_policy": "Law & policy",
}

# Presentation only: the web UI renders one headed section per group so two
# dozen checkboxes stay scannable. Every field key must appear exactly once
# (a test enforces this).
FIELD_GROUPS: dict[str, list[str]] = {
    "General": ["multidisciplinary"],
    "Life sciences": [
        "medicine",
        "biology",
        "microbiome",
        "immunology",
        "bioinformatics",
        "neuroscience",
        "public_health",
        "agriculture_food",
        "ecology_evolution",
    ],
    "Physical sciences": [
        "chemistry",
        "physics",
        "materials_engineering",
        "earth_environment",
    ],
    "Computing": [
        "ai_ml",
        "computer_science",
        "security_privacy",
        "statistics_data_science",
        "robotics",
        "hci",
    ],
    "Social sciences": ["psychology", "economics_social", "education", "law_policy"],
}

# Retired field keys → the keys that replaced them. Keeps a saved UI selection
# or an existing API caller working across a field split.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "cs_ai": ("ai_ml", "computer_science"),
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
    # Microbiology / immunology
    "isme journal": "the isme journal",
    "isme j": "the isme journal",
    "journal of experimental medicine": "the journal of experimental medicine",
    "j exp med": "the journal of experimental medicine",
    "journal of immunology": "the journal of immunology",
    "cellular & molecular immunology": "cellular and molecular immunology",
    "appl environ microbiol": "applied and environmental microbiology",
    # Computing
    "jmlr": "journal of machine learning research",
    "tpami": "ieee transactions on pattern analysis and machine intelligence",
    "neurips": "neural information processing systems",
    "nips": "neural information processing systems",
    "advances in neural information processing systems": "neural information processing systems",
    "icml": "international conference on machine learning",
    "iclr": "international conference on learning representations",
    "cacm": "communications of the acm",
    "jair": "journal of artificial intelligence research",
    "tochi": "acm transactions on computer-human interaction",
    "ijrr": "the international journal of robotics research",
    "usenix security": "usenix security symposium",
    "ndss": "network and distributed system security symposium",
    "tifs": "ieee transactions on information forensics and security",
    "popets": "proceedings on privacy enhancing technologies",
    # Statistics
    "jasa": "journal of the american statistical association",
    "annals of statistics": "the annals of statistics",
    "annals of applied statistics": "the annals of applied statistics",
    "jrssb": "journal of the royal statistical society series b (statistical methodology)",
    "journal of the royal statistical society series b": (
        "journal of the royal statistical society series b (statistical methodology)"
    ),
    # Economics / law
    "aer": "american economic review",
    "qje": "the quarterly journal of economics",
    "quarterly journal of economics": "the quarterly journal of economics",
    "jpe": "journal of political economy",
    "review of economic studies": "the review of economic studies",
    "journal of finance": "the journal of finance",
    "yale law journal": "the yale law journal",
    "journal of legal studies": "the journal of legal studies",
    # Leading-article variants OpenAlex sometimes reports without the article.
    "journal of neuroscience": "the journal of neuroscience",
    "embo journal": "the embo journal",
    "plant cell": "the plant cell",
    "economic journal": "the economic journal",
    "astrophysical journal": "the astrophysical journal",
}


def normalize_journal_name(name: str | None) -> str:
    """Lowercase, strip punctuation/whitespace, and resolve known aliases.

    Internal periods are treated as separators rather than characters: OpenAlex
    reports the Nature Reviews family as `"Nature reviews. Immunology"`, and
    abbreviated forms arrive as `"J. Dairy Sci."`. Both then collapse onto the
    same normalized form as the spaced spelling, so one entry covers each.
    """
    if not name:
        return ""
    cleaned = name.lower().strip()
    # Periods separate words rather than belonging to them.
    cleaned = cleaned.replace(".", " ")
    # Collapse internal whitespace and strip stray punctuation at the edges.
    # Leading-article differences ("Lancet" vs "The Lancet") are resolved via
    # ALIASES rather than by stripping, so the canonical set stays readable.
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .,:;-")
    return ALIASES.get(cleaned, cleaned)


class UnknownFieldError(ValueError):
    """Raised when a caller asks for a field key that does not exist."""


def resolve_fields(fields: list[str]) -> list[str]:
    """Expand retired field keys via `FIELD_ALIASES`, preserving order.

    Lets `fields=["cs_ai"]` keep working after that field was split, so a saved
    UI selection or an older API caller does not start erroring.
    """
    resolved: list[str] = []
    for key in fields:
        for expanded in FIELD_ALIASES.get(key, (key,)):
            if expanded not in resolved:
                resolved.append(expanded)
    return resolved


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
                everything, so only `extra_journals` applies. Retired keys are
                expanded via `FIELD_ALIASES`.
            extra_journals: Free-text journal titles, normalized the same way
                incoming paper journal names are so they match on equal terms.

        Raises:
            UnknownFieldError: if a field key is not in `JOURNALS_BY_FIELD`.
        """
        selected: frozenset[str] | None = None
        if fields is not None:
            expanded = resolve_fields(fields)
            unknown = sorted(set(expanded) - set(JOURNALS_BY_FIELD))
            if unknown:
                raise UnknownFieldError(
                    f"Unknown field(s): {', '.join(unknown)}. "
                    f"Valid fields: {', '.join(sorted(JOURNALS_BY_FIELD))}."
                )
            selected = frozenset(expanded)

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
