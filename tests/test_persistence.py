"""Tests for report writing (`app/persistence.py`)."""

from __future__ import annotations

import json

import pytest

from app.persistence import _format_authors, _render_markdown, _slugify, save_research_output


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert _slugify("Does Fasting Work?") == "does-fasting-work"

    def test_collapses_runs_of_punctuation(self):
        assert _slugify("A -- B!!! C") == "a-b-c"

    def test_truncates_without_a_trailing_hyphen(self):
        slug = _slugify("word " * 40, max_len=20)
        assert len(slug) <= 20
        assert not slug.endswith("-")

    @pytest.mark.parametrize("junk", ["", "???", "   "])
    def test_falls_back_when_nothing_survives(self, junk):
        assert _slugify(junk) == "research"


class TestFormatAuthors:
    def test_no_authors(self):
        assert _format_authors([]) == "Unknown authors"

    def test_three_or_fewer_listed_in_full(self):
        assert _format_authors(["A", "B", "C"]) == "A, B, C"

    def test_four_or_more_abbreviated(self):
        assert _format_authors(["A", "B", "C", "D"]) == "A, B, C, et al."


class TestRenderMarkdown:
    def test_includes_question_summary_and_count(self):
        md = _render_markdown("Why?", "Because.", [{"title": "T"}], "2026-01-01T00:00:00+00:00")
        assert "**Question:** Why?" in md
        assert "Because." in md
        assert "## Selected Papers (1)" in md

    def test_renders_a_citation_line(self):
        papers = [
            {
                "title": "Fasting and insulin",
                "authors": ["Ada L", "Grace H"],
                "journal_name": "Cell Metabolism",
                "year": 2018,
                "citation_count": 42,
                "doi": "10.1/xyz",
            }
        ]
        md = _render_markdown("Q", "S", papers, "now")
        assert "**Fasting and insulin**" in md
        assert "Ada L, Grace H" in md
        assert "*Cell Metabolism* (2018)" in md
        assert "Citations: 42" in md
        assert "https://doi.org/10.1/xyz" in md

    def test_falls_back_when_metadata_is_missing(self):
        md = _render_markdown("Q", "S", [{}], "now")
        assert "Untitled" in md
        assert "Unknown authors" in md
        assert "Unknown venue" in md
        assert "n.d." in md

    def test_states_when_nothing_was_found(self):
        assert "_No papers met the high-impact criteria._" in _render_markdown("Q", "S", [], "now")


class TestSaveResearchOutput:
    def test_writes_both_files_and_reports_paths(self, tmp_path):
        papers = [{"title": "T", "authors": ["A"], "journal_name": "Nature", "year": 2021}]
        result = save_research_output("Does it work?", "Yes.", papers, output_dir=str(tmp_path))

        assert result["paper_count"] == 1
        json_path = result["json_path"]
        md_path = result["markdown_path"]
        assert json_path.endswith(".json")
        assert md_path.endswith(".md")

        payload = json.loads(open(json_path, encoding="utf-8").read())
        assert payload["question"] == "Does it work?"
        assert payload["summary"] == "Yes."
        assert payload["papers"] == papers
        assert payload["generated_at"] == result["generated_at"]

        assert "Does it work?" in open(md_path, encoding="utf-8").read()

    def test_creates_the_output_directory(self, tmp_path):
        target = tmp_path / "nested" / "deeper"
        save_research_output("Q", "S", [], output_dir=str(target))
        assert target.is_dir()

    def test_filename_carries_a_slug_of_the_question(self, tmp_path):
        result = save_research_output("Does fasting help?", "S", [], output_dir=str(tmp_path))
        assert "does-fasting-help" in result["json_path"]
