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


def _render_markdown(question: str, summary: str, papers: list[dict], generated_at: str) -> str:
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
    lines.append("")
    return "\n".join(lines)


def save_research_output(
    question: str,
    summary: str,
    papers: list[dict],
    output_dir: str | None = None,
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
    }
    json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_render_markdown(question, summary, papers, generated_at), encoding="utf-8")

    return {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "paper_count": len(papers),
        "generated_at": generated_at,
    }
