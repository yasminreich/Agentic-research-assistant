"""Tool functions the agents call.

`ResearchTools` bundles the two functions exposed to the agents together with
the per-run state they share:

  - `search_literature`   — Proxy executes this; calls OpenAlex, applies the
    high-impact filter and recency dedup, and returns curated candidates.
  - `save_research_report` — Proxy executes this; resolves the paper ids the
    Researcher selected back to full metadata and writes the report to disk.

A fresh `ResearchTools` is created per research run so state never leaks between
concurrent requests.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Annotated

from .config import Settings, get_settings
from .filters import deduplicate_by_recency, filter_high_impact, rejected_journal_counts
from .journals import DEFAULT_POLICY, JournalPolicy, normalize_journal_name
from .openalex_client import OpenAlexClient, OpenAlexError
from .persistence import save_research_output
from .verification import bare_id, build_report

logger = logging.getLogger(__name__)

# How much abstract to show the Researcher per candidate (chars).
ABSTRACT_PREVIEW_CHARS = 1200


class ResearchTools:
    """Per-run tool implementations with shared state."""

    def __init__(
        self,
        question: str,
        client: OpenAlexClient | None = None,
        settings: Settings | None = None,
        policy: JournalPolicy = DEFAULT_POLICY,
        min_year: int | None = None,
    ) -> None:
        self.question = question
        self.settings = settings or get_settings()
        self.client = client or OpenAlexClient()
        # Which journals this run accepts, and the earliest year it considers.
        # Both are per-run so one user's narrow search cannot affect another's.
        self.policy = policy
        self.min_year = min_year if min_year is not None else self.settings.min_year
        # Journals dropped by the policy this run, aggregated across searches,
        # so a zero-result run can tell the user what it turned away.
        self.rejected: Counter[str] = Counter()
        # Normalized journal names this run has actually seen a paper from.
        # Used to tell the user which of their typed journals never matched —
        # a misspelling used to fail completely silently.
        self.seen_journals: set[str] = set()
        # Full metadata of every curated paper we've surfaced, keyed by id.
        self.collected: dict[str, dict] = {}
        # Result of the most recent save_research_report call.
        self.last_report: dict | None = None

    # --- tool: search -------------------------------------------------------

    def search_literature(
        self,
        query: Annotated[str, "Free-text search query for the literature database."],
        year_from: Annotated[
            int | None,
            "Only include papers published in this year or later. Defaults to the "
            "configured minimum year.",
        ] = None,
        limit: Annotated[
            int | None,
            "Maximum number of papers to retrieve for this query (the API caps this at 200).",
        ] = None,
    ) -> str:
        """Search OpenAlex, filter to high-impact journals,
        deduplicate by recency, and return curated candidate papers as JSON.
        """
        effective_year = year_from if year_from is not None else self.min_year
        effective_limit = limit if limit is not None else self.settings.max_papers_per_query

        try:
            raw = self.client.search(query, limit=effective_limit, year_from=effective_year)
        except OpenAlexError as exc:
            logger.warning("OpenAlex search failed for %r: %s", query, exc)
            return json.dumps({"query": query, "error": str(exc), "papers": []}, ensure_ascii=False)

        for paper in raw:
            normalized = normalize_journal_name(paper.journal_name)
            if normalized:
                self.seen_journals.add(normalized)

        high_impact = filter_high_impact(raw, self.policy)
        curated = deduplicate_by_recency(high_impact)

        # Record what the policy turned away, for the "why did I get nothing?"
        # explanation the caller shows the user.
        rejected = rejected_journal_counts(raw, self.policy, limit=50)
        for entry in rejected:
            self.rejected[entry["journal"]] += entry["count"]

        # Remember full metadata so we can resolve ids at save time.
        candidates = []
        for paper in curated:
            full = paper.to_dict()
            self.collected[paper.paper_id] = full
            abstract = paper.abstract or ""
            candidates.append(
                {
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "year": paper.year,
                    "journal": paper.journal_name,
                    "citation_count": paper.citation_count,
                    "abstract": abstract[:ABSTRACT_PREVIEW_CHARS],
                }
            )

        return json.dumps(
            {
                "query": query,
                "total_retrieved": len(raw),
                "high_impact_count": len(high_impact),
                "curated_count": len(curated),
                "journal_policy": self.policy.describe(),
                "rejected_journals": rejected[:10],
                "papers": candidates,
            },
            ensure_ascii=False,
        )

    # --- tool: save ---------------------------------------------------------

    def save_research_report(
        self,
        summary: Annotated[
            str,
            "The comprehensive scientific summary answering the research question.",
        ],
        paper_ids: Annotated[
            list[str],
            "The paper_id values of the relevant papers to include in the report.",
        ],
        question: Annotated[str, "The original research question being answered."] = "",
        evidence: Annotated[
            list[dict] | None,
            (
                "Supporting evidence for the summary's main claims: a list of "
                '{"paper_id": "W...", "quote": "..."} objects, where each quote is '
                "copied VERBATIM from that paper's abstract. Quotes are checked "
                "against the abstract automatically."
            ),
        ] = None,
    ) -> str:
        """Resolve the selected paper ids to full metadata, verify the summary's
        citations and quotes, and write the report to disk. Returns a
        confirmation message with the saved file paths.
        """
        selected = [self.collected[pid] for pid in paper_ids if pid in self.collected]
        unknown = [pid for pid in paper_ids if pid not in self.collected]
        if unknown:
            logger.warning("save_research_report got unknown paper ids: %s", unknown)

        # Mechanical checks on what the model wrote. These never block the save:
        # the point is to report what could not be confirmed, not to gate on it.
        verification = build_report(
            summary=summary,
            selected_ids=[p["paper_id"] for p in selected],
            retrieved_ids=set(self.collected),
            evidence=evidence or [],
            collected=self.collected,
            unknown_paper_ids=unknown,
        )
        if not verification["ok"]:
            logger.warning("Verification flagged issues: %s", verification)

        # Attach each verified quote to its paper so the UI and the Markdown
        # report can show the evidence next to the source it came from.
        # Keyed by bare id: papers carry the full OpenAlex URL, the model cites
        # the short form.
        quotes_by_paper: dict[str, list[dict]] = {}
        for item in verification["quotes"]["results"]:
            quotes_by_paper.setdefault(bare_id(item["paper_id"]), []).append(
                {"quote": item["quote"], "status": item["status"]}
            )
        for paper in selected:
            paper["evidence"] = quotes_by_paper.get(bare_id(paper["paper_id"]), [])

        result = save_research_output(
            question=question or self.question,
            summary=summary,
            papers=selected,
            output_dir=self.settings.output_dir,
            verification=verification,
        )
        result["summary"] = summary
        result["papers"] = selected
        result["rejected_journals"] = self.top_rejected_journals()
        result["unmatched_journals"] = self.unmatched_journals()
        result["verification"] = verification
        self.last_report = result

        return (
            f"Report saved with {result['paper_count']} papers. "
            f"JSON: {result['json_path']} | Markdown: {result['markdown_path']}"
        )

    # --- reporting ----------------------------------------------------------

    def top_rejected_journals(self, limit: int = 10) -> list[dict]:
        """Journals the policy excluded across this run, most frequent first."""
        return [{"journal": name, "count": n} for name, n in self.rejected.most_common(limit)]

    def unmatched_journals(self) -> list[str]:
        """The caller's named journals that no paper in this run came from.

        Usually a typo or a title OpenAlex spells differently. Reporting them
        turns a silent no-op into something the user can fix; without this, a
        misspelled entry looks identical to a journal that simply had no
        relevant papers.
        """
        return sorted(self.policy.extra - self.seen_journals)
