# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## What this project is

An **automated research assistant**: a FastAPI backend that answers a research
question by running a two-agent literature review.

- **Researcher Agent** — `AssistantAgent` powered by Claude (`claude-opus-4-8`),
  via the AG2 (maintained classic AutoGen) framework. Plans search queries,
  judges relevance, clusters papers that reach the same conclusion (keeping the
  most recent), and writes a comprehensive scientific summary.
- **Proxy Agent** — `UserProxyAgent` that executes the registered tool functions
  (no human input). It calls the **Paperclip** database — our internal codename
  for the **OpenAlex** Works API (`api.openalex.org/works`, keyless).

Results are filtered to a **curated high-impact journal allowlist**,
**deduplicated by recency**, and saved as JSON + Markdown reports under
`output/`.

## Request flow

```
POST /research {question}
  → workflow.run_research(question)
     → AG2 chat: Researcher plans queries
        → Proxy runs search_literature  → PaperclipClient (OpenAlex)
                                         → filter_high_impact + deduplicate_by_recency
        → Researcher judges relevance, writes summary
        → Proxy runs save_research_report → output/<timestamp>-<slug>.{json,md}
```

**Design split:** deterministic steps (API calls, the allowlist, title-level
dedup + recency) live in plain Python so they're auditable. Semantic steps
(relevance, "same conclusion") are the Researcher's judgment.

## Key files

| File | Role |
|---|---|
| `app/config.py` | Settings via `pydantic-settings` (reads `.env`). |
| `app/paperclip_client.py` | `PaperclipClient` → OpenAlex Works API; normalizes to the `Paper` dataclass; backoff/retry. **The data source is isolated here** — swapping APIs means editing only this file (keep `Paper` + `search()` signature stable). |
| `app/journals.py` | `HIGH_IMPACT_JOURNALS` allowlist + aliases + `is_high_impact()`. **Single source of truth for the reputable-journal policy.** |
| `app/filters.py` | `filter_high_impact()` and `deduplicate_by_recency()`. |
| `app/tools.py` | `ResearchTools`: `search_literature` / `save_research_report` (per-run shared state). |
| `app/agents.py` | Builds Researcher + Proxy, registers tools, defines the Anthropic `llm_config` and the Researcher system prompt. |
| `app/anthropic_compat.py` | **Required shim** — see Conventions. |
| `app/workflow.py` | `run_research(question)` orchestration. |
| `app/persistence.py` | Writes the JSON + Markdown reports. |
| `app/server.py` | FastAPI app: `POST /research`, `GET /health`. |
| `run.py` | uvicorn launcher. |
| `scripts/smoke_test.py` | Pre-flight checks (OpenAlex search + one Claude call). |

## Setup & run (summary — full details in README.md)

- `.env` is **not** committed (gitignored). Create it from `.env.example` and set
  `ANTHROPIC_API_KEY`. OpenAlex needs no key; `OPENALEX_MAILTO` is optional.
- Two terminals: `python run.py` (server) in one; the `POST /research` request in
  another. The research **question is passed in the request body**, not config.
- Smoke test before a full run: `python -m scripts.smoke_test`.

## Conventions & gotchas (read before editing)

- **Claude model is `claude-opus-4-8`.** Use the exact ID; don't downgrade.
- **Do NOT send `temperature`/`top_p`/`top_k` to Claude.** Opus 4.7/4.8/Fable
  reject them with a 400. AG2 injects `temperature=1.0` by default, so
  `app/anthropic_compat.py` patches AG2's `load_config` to strip those params for
  affected models. **Keep this shim** and keep `patch_ag2_anthropic_sampling()`
  called in `agents.py`. If Claude calls start 400-ing on sampling params, that
  patch is the place to look.
- **AG2 is pinned `<1.0`.** ag2 1.0 renamed the top-level package `autogen` →
  `ag2`, so every `import autogen` in `app/` breaks against it. Don't lift the
  bound without migrating those imports and re-checking the `load_config`
  patch. CI caught this because the old `>=0.7` floor let a fresh install
  resolve 1.0.
- **Keep the data source behind `PaperclipClient`.** `journals.py`, `filters.py`,
  `tools.py`, `agents.py`, `workflow.py`, `persistence.py` all depend only on the
  `Paper` dataclass — preserve it when changing APIs.
- **High-impact policy** changes go in `journals.py` only.
- **Secrets:** never commit `.env` or hardcode keys. `.gitignore` covers `.env`,
  `output/`, and `~$*.docx`. Before any commit or push, scan staged content for
  `sk-ant-` and confirm `.env` is not tracked.
- **Verify changes** by running `python -m scripts.smoke_test` (and, for behavior
  changes, a full `POST /research` run).

## Git workflow — commit regularly

- **Commit in small, logical increments** as you complete each coherent change,
  rather than batching many unrelated edits into one large commit.
- Write clear, imperative commit messages (e.g. `docs: ...`, `fix: ...`,
  `feat: ...`) describing what changed and why.
- **Always scan staged content for secrets before committing**, and re-scan the
  full history before any push (this repo is public).
- Remote is `origin` → `https://github.com/yasminreich/Agentic-research-assistant`
  (branch `main`). Push after committing when work is in a working state.
