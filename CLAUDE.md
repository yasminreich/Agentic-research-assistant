# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

**What this project is and how to run it live in [README.md](README.md).** This
file covers only what a contributor needs that the README doesn't say.

## Architecture in one line

`POST /research` → `workflow.run_research()` → AG2 chat between a **Researcher**
(Claude) and a **Proxy** (runs the tools) → `PaperclipClient` hits OpenAlex →
`filters` applies the journal policy and recency dedup → `persistence` writes
JSON + Markdown to `output/`.

**Design split:** deterministic steps (API calls, the allowlist, title-level dedup
+ recency) live in plain Python so they're auditable. Semantic steps (relevance,
"same conclusion") are the Researcher's judgment. Keep that line where it is.

## Key files

| File | Role |
|---|---|
| `app/config.py` | Settings via `pydantic-settings` (reads `.env`). |
| `app/paperclip_client.py` | `PaperclipClient` → OpenAlex Works API; normalizes to the `Paper` dataclass; backoff/retry. **The data source is isolated here** — swapping APIs means editing only this file (keep `Paper` + `search()` signature stable). |
| `app/journals.py` | `JOURNALS_BY_FIELD`, `FIELD_LABELS`, `ALIASES`, and `JournalPolicy`. **Single source of truth for the reputable-journal policy.** |
| `app/filters.py` | `filter_high_impact()`, `deduplicate_by_recency()`, `rejected_journal_counts()`. |
| `app/tools.py` | `ResearchTools`: `search_literature` / `save_research_report` (per-run shared state). |
| `app/agents.py` | Builds Researcher + Proxy, registers tools, defines the Anthropic `llm_config` and the Researcher system prompt template. |
| `app/anthropic_compat.py` | **Required shim** — see Conventions. |
| `app/workflow.py` | `run_research(question, *, fields, extra_journals, min_year)`. |
| `app/persistence.py` | Writes the JSON + Markdown reports. |
| `app/server.py` | FastAPI app: `POST /research`, `GET /journals`, `GET /config`, `GET /health`. |
| `app/static/index.html` | The whole web UI — one file, vanilla JS, no build step. |
| `tests/` | 233 offline tests. No network, no API key. |
| `scripts/smoke_test.py` | Live pre-flight checks (real OpenAlex search + one real Claude call). |

## Conventions & gotchas (read before editing)

- **Claude model is `claude-opus-4-8`.** Use the exact ID; don't downgrade.
- **Do NOT send `temperature`/`top_p`/`top_k` to Claude.** Opus 4.7/4.8/Fable
  reject them with a 400. AG2 injects `temperature=1.0` by default, so
  `app/anthropic_compat.py` patches AG2's `load_config` to strip those params for
  affected models. **Keep this shim** and keep `patch_ag2_anthropic_sampling()`
  called in `agents.py`. If Claude calls start 400-ing on sampling params, that
  patch is the place to look — and `tests/test_anthropic_compat.py` pins the
  AG2 internal it depends on, so an upgrade that breaks it fails the build.
- **Keep the data source behind `PaperclipClient`.** `journals.py`, `filters.py`,
  `tools.py`, `agents.py`, `workflow.py`, `persistence.py` all depend only on the
  `Paper` dataclass — preserve it when changing APIs.
- **High-impact policy** changes go in `journals.py` only. The web UI builds its
  checkboxes from `GET /journals`, so adding a field there needs no UI change —
  but it does need an entry in both `JOURNALS_BY_FIELD` and `FIELD_LABELS`
  (a test enforces that they stay in sync).
- **Journal matching is exact after normalization, not substring.** `"dairy
  science"` will never match *Journal of Dairy Science*. Add the full lowercase
  title, and use `ALIASES` for abbreviations and leading-article variants.
- **`fields` has three states.** `None` = every field (the controls were never
  touched). A list = those fields. An **empty list** = no field, so only
  `extra_journals` applies. Don't collapse the last two.
- **Secrets:** never commit `.env` or hardcode keys. `.gitignore` covers `.env`,
  `output/`, and `project scope.docx`. Before any commit or push, scan staged
  content for `sk-ant-` and confirm `.env` is not tracked.

## Testing

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                                    # offline; safe to run anywhere
ruff check . && ruff format --check .
```

CI (`.github/workflows/ci.yml`) runs exactly those on Python 3.10/3.11/3.12.

**Keep the suite offline.** The two injection seams that make that possible are
`PaperclipClient(session=...)` and `ResearchTools(client=...)` — don't remove
them. Anything needing a real API call belongs in `scripts/smoke_test.py`, which
is run by hand.

For behaviour changes, also do a real `POST /research` run before calling it done.

## Git workflow

- **Commit in small, logical increments** as you complete each coherent change,
  rather than batching many unrelated edits into one large commit.
- Write clear, imperative commit messages (`docs:`, `fix:`, `feat:`, `test:`,
  `chore:`) describing what changed and why.
- **Work on a branch and open a PR** rather than pushing to `main`.
- **Always scan staged content for secrets before committing**, and re-scan the
  full history before any push (this repo is public).
- Remote is `origin` → `https://github.com/yasminreich/Agentic-research-assistant`
  (branch `main`).
