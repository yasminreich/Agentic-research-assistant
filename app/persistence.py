"""Persist research output (summary + selected papers) to disk.

Writes two files per run under the configured output directory:
  - `<timestamp>-<slug>.json` — machine-readable: question, summary, full paper
    metadata.
  - `<timestamp>-<slug>.md`   — human-readable scientific report with references.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings


def _slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "research"


def _format_authors(authors: list[str]) -> str:
    if not authors:
        return "Unknown authors"
    if len(authors) <= 3:
        return ", ".join(authors)
    return f"{', '.join(authors[:3])}, et al."


def _render_verification(verification: dict | None) -> list[str]:
    """A short, honest audit block for the Markdown report.

    States what was checked and what could not be confirmed. `no_abstract` is
    reported as uncheckable, never as fabricated — OpenAlex has no abstract for
    many records.
    """
    if not verification:
        return []

    citations = verification.get("citations", {})
    quotes = verification.get("quotes", {})
    tally = quotes.get("tally", {})
    lines = ["## Verification", ""]

    cited = citations.get("cited_count", 0)
    if cited:
        lines.append(
            f"- {citations.get('verified_count', 0)} of {cited} citations in the summary "
            "match papers this run actually retrieved."
        )
    unverified = citations.get("unverified", [])
    if unverified:
        lines.append(
            f"- **{len(unverified)} citation(s) could not be verified** "
            f"(never returned by any search): {', '.join(unverified)}"
        )

    total_quotes = quotes.get("total", 0)
    if total_quotes:
        lines.append(
            f"- {tally.get('supported', 0)} of {total_quotes} supporting quotes were found "
            "in the cited paper's abstract."
        )
    if tally.get("not_found"):
        lines.append(
            f"- **{tally['not_found']} quote(s) were NOT found** in the abstract they "
            "were attributed to."
        )
    if tally.get("no_abstract"):
        lines.append(
            f"- {tally['no_abstract']} quote(s) could not be checked because OpenAlex "
            "has no abstract for that paper. This is not evidence of a problem."
        )
    unknown = verification.get("unknown_paper_ids", [])
    if unknown:
        lines.append(
            f"- **{len(unknown)} requested paper id(s) did not exist** and were "
            f"dropped: {', '.join(unknown)}"
        )

    lines += [
        "",
        "_Titles, journals, years and DOIs come from OpenAlex and are not written by "
        "the model. The summary is the model's synthesis — open a DOI to check any "
        "claim._",
        "",
    ]
    return lines


def _render_markdown(
    question: str,
    summary: str,
    papers: list[dict],
    generated_at: str,
    verification: dict | None = None,
) -> str:
    lines = [
        "# Research Report",
        "",
        f"**Question:** {question}",
        "",
        f"_Generated: {generated_at}_",
        "",
        "## Scientific Summary",
        "",
        summary.strip(),
        "",
        *_render_verification(verification),
        f"## Selected Papers ({len(papers)})",
        "",
    ]
    if not papers:
        lines.append("_No papers met the high-impact criteria._")
    for i, paper in enumerate(papers, start=1):
        authors = _format_authors(paper.get("authors") or [])
        journal = paper.get("journal_name") or paper.get("venue") or "Unknown venue"
        year = paper.get("year") or "n.d."
        citations = paper.get("citation_count", 0)
        title = paper.get("title", "Untitled")
        ref = f"{i}. **{title}** — {authors}. *{journal}* ({year}). Citations: {citations}."
        link = paper.get("doi") or paper.get("url")
        if link:
            prefix = "https://doi.org/" if paper.get("doi") else ""
            ref += f" [{link}]({prefix}{link})"
        lines.append(ref)
        for item in paper.get("evidence") or []:
            marker = {"supported": "verified", "not_found": "NOT FOUND in abstract"}.get(
                item.get("status", ""), item.get("status", "")
            )
            lines.append(f"    > {item.get('quote', '')}")
            lines.append(f"    > — quote {marker}")
    lines.append("")
    return "\n".join(lines)


def save_research_output(
    question: str,
    summary: str,
    papers: list[dict],
    output_dir: str | None = None,
    verification: dict | None = None,
) -> dict:
    """Write JSON + Markdown reports and return paths + metadata.

    Returns a dict with `json_path`, `markdown_path`, `paper_count`,
    `generated_at`.
    """
    settings = get_settings()
    out_dir = Path(output_dir or settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    stem = f"{now.strftime('%Y%m%d-%H%M%S')}-{_slugify(question)}"

    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"

    json_payload = {
        "question": question,
        "generated_at": generated_at,
        "summary": summary,
        "papers": papers,
        # Saved alongside the report so it stays auditable after the fact.
        "verification": verification or {},
    }
    json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_render_markdown(question, summary, papers, generated_at), encoding="utf-8")

    return {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "paper_count": len(papers),
        "generated_at": generated_at,
    }
