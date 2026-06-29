# Automated Research Assistant

A backend service that answers a research question by automatically reviewing the
scientific literature with a multi-agent system.

- **Researcher Agent** (Claude, via AG2 `AssistantAgent`) — plans search queries,
  judges relevance, clusters papers that reach the same conclusion, and writes a
  comprehensive scientific summary.
- **Proxy Agent** (AG2 `UserProxyAgent`) — executes the actual API calls to the
  **Paperclip** database (our codename for [OpenAlex](https://docs.openalex.org/),
  which is free and needs no API key).

The system targets **high-impact, reputable journals**, **deduplicates by
recency** (when several papers reach the same conclusion, the most recent wins),
and **saves** the summary plus all selected papers to disk.

## How it works

```
POST /research {question}
   → Researcher plans queries
   → Proxy calls Paperclip (OpenAlex)
        → results filtered to a curated high-impact journal allowlist
        → near-duplicate papers collapsed, most recent kept
   → Researcher judges relevance + writes scientific summary
   → Proxy saves report  → output/<timestamp>-<slug>.json + .md
```

Deterministic steps (API calls, the high-impact allowlist, title-level dedup +
recency) live in plain Python so they're auditable. Semantic steps (relevance,
"same conclusion") are the Researcher's judgment.

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt
cp .env.example .env   # then edit .env
```

Set `ANTHROPIC_API_KEY` in `.env` — that's the only required credential. The
literature backend (OpenAlex) needs **no API key**. Optionally set
`OPENALEX_MAILTO` to your email to use OpenAlex's faster "polite pool".

## Run

```bash
python run.py            # serves on http://0.0.0.0:8000
```

Then:

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"question": "Does intermittent fasting improve insulin sensitivity in adults?"}'
```

Response:

```json
{
  "question": "...",
  "summary": "...",
  "paper_count": 7,
  "saved": true,
  "json_path": "output/20260628-...-does-intermittent-fasting.json",
  "markdown_path": "output/20260628-...-does-intermittent-fasting.md"
}
```

The full report (summary + every selected paper with authors, journal, year,
citations, DOI) is written to the `output/` directory in both JSON and Markdown.

## Smoke test before a full run

```bash
python -m scripts.smoke_test
```

This checks the Paperclip search path (no key needed) and — if
`ANTHROPIC_API_KEY` is set — a single Claude call through AG2.

## Configuration

All settings come from environment variables / `.env` (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Claude access for the Researcher. |
| `OPENALEX_MAILTO` | — | Optional; your email for OpenAlex's faster polite pool. |
| `CLAUDE_MODEL` | `claude-opus-4-8` | Model for the Researcher. |
| `MIN_YEAR` | `2015` | Earliest publication year considered. |
| `MAX_PAPERS_PER_QUERY` | `50` | Results requested per query (API caps at 200). |
| `MAX_AGENT_TURNS` | `15` | Safety cap on automatic agent turns per run. |
| `OUTPUT_DIR` | `output` | Where reports are written. |

## Editing the high-impact journal policy

The reputable-journal allowlist is the single source of truth in
[`app/journals.py`](app/journals.py). Add or remove entries in
`HIGH_IMPACT_JOURNALS` (normalized, lowercase) and `ALIASES` (abbreviations).

## Project layout

```
app/
  config.py            # settings (pydantic-settings)
  paperclip_client.py  # PaperclipClient → OpenAlex Works API
  journals.py          # high-impact journal allowlist + matcher
  filters.py           # high-impact filter + recency dedup
  tools.py             # search_literature / save_research_report tools
  agents.py            # Researcher + Proxy agents, Anthropic llm_config
  workflow.py          # run_research() orchestration
  persistence.py       # JSON + Markdown report writer
  server.py            # FastAPI app
scripts/smoke_test.py  # pre-flight checks
run.py                 # uvicorn launcher
```

## Troubleshooting

**`400` error about `temperature` / `top_p` from Claude.** Opus 4.8 (and other
4.7+/Fable models) reject sampling parameters, and AG2 sends `temperature` by
default. This is handled automatically by `app/anthropic_compat.py`, which strips
those params for affected models. If you somehow still hit it, set
`CLAUDE_MODEL=claude-sonnet-4-6` in `.env` (Sonnet 4.6 accepts `temperature`).
Run `python -m scripts.smoke_test` to confirm the LLM path before the server.

**OpenAlex `429`s.** OpenAlex is keyless with generous limits, but under heavy
use it can still rate-limit. The client backs off and retries automatically;
setting `OPENALEX_MAILTO` to your email moves you into the faster polite pool.
