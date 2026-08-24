"""Tool functions the agents call.

`ResearchTools` bundles the two functions exposed to the agents together with
the per-run state they share:

  - `search_literature`   — Proxy executes this; calls Paperclip, applies the
    high-impact filter and recency dedup, and returns curated candidates.
  - `save_research_report` — Proxy executes this; resolves the paper ids the
    Researcher selected back to full metadata and writes the report to disk.

A fresh `ResearchTools` is created per research run so state never leaks between
concurrent requests.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

from .config import Settings, get_settings
from .filters import deduplicate_by_recency, filter_high_impact
from .paperclip_client import PaperclipClient, PaperclipError
from .persistence import save_research_output

logger = logging.getLogger(__name__)

# How much abstract to show the Researcher per candidate (chars).
ABSTRACT_PREVIEW_CHARS = 1200


class ResearchTools:
    """Per-run tool implementations with shared state."""

    def __init__(
        self,
        question: str,
        client: PaperclipClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.question = question
        self.settings = settings or get_settings()
        self.client = client or PaperclipClient()
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
        """Search the Paperclip database, filter to high-impact journals,
        deduplicate by recency, and return curated candidate papers as JSON.
        """
        effective_year = year_from if year_from is not None else self.settings.min_year
        effective_limit = limit if limit is not None else self.settings.max_papers_per_query

        try:
            raw = self.client.search(query, limit=effective_limit, year_from=effective_year)
        except PaperclipError as exc:
            logger.warning("Paperclip search failed for %r: %s", query, exc)
            return json.dumps({"query": query, "error": str(exc), "papers": []}, ensure_ascii=False)

        high_impact = filter_high_impact(raw)
        curated = deduplicate_by_recency(high_impact)

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
    ) -> str:
        """Resolve the selected paper ids to full metadata and write the report
        to disk. Returns a confirmation message with the saved file paths.
        """
        selected = [self.collected[pid] for pid in paper_ids if pid in self.collected]
        unknown = [pid for pid in paper_ids if pid not in self.collected]
        if unknown:
            logger.warning("save_research_report got unknown paper ids: %s", unknown)

        result = save_research_output(
            question=question or self.question,
            summary=summary,
            papers=selected,
            output_dir=self.settings.output_dir,
        )
        result["summary"] = summary
        result["papers"] = selected
        self.last_report = result

        return (
            f"Report saved with {result['paper_count']} papers. "
            f"JSON: {result['json_path']} | Markdown: {result['markdown_path']}"
        )
