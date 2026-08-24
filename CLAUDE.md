# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

**What this project is and how to run it live in [README.md](README.md).** This
file covers only what a contributor needs that the README doesn't say.

## Architecture in one line

`POST /research` → `workflow.run_research()` → AG2 chat between a **Researcher**
(Claude) and a **Proxy** (runs the tools) → `OpenAlexClient` hits OpenAlex →
`filters` applies the journal policy and recency dedup → `persistence` writes
JSON + Markdown to `output/`.

**Design split:** deterministic steps (API calls, the allowlist, title-level dedup
+ recency) live in plain Python so they're auditable. Semantic steps (relevance,
"same conclusion") are the Researcher's judgment. Keep that line where it is.

## Key files

| File | Role |
|---|---|
| `app/config.py` | Settings via `pydantic-settings` (reads `.env`). |
| `app/openalex_client.py` | `OpenAlexClient` → OpenAlex Works API; normalizes to the `Paper` dataclass; backoff/retry. **The data source is isolated here** — swapping APIs means editing only this file (keep `Paper` + `search()` signature stable). |
| `app/journals.py` | `JOURNALS_BY_FIELD` (24 fields, 255 journals), `FIELD_LABELS`, `FIELD_GROUPS`, `FIELD_ALIASES`, `ALIASES`, `JournalPolicy`. **Single source of truth for the reputable-journal policy.** |
| `app/filters.py` | `filter_high_impact()`, `deduplicate_by_recency()`, `rejected_journal_counts()`. |
| `app/verification.py` | Citation + quote checks on the model's output. Pure functions, no network. |
| `app/tools.py` | `ResearchTools`: `search_literature` / `save_research_report` (per-run shared state). |
| `app/agents.py` | Builds Researcher + Proxy, registers tools, defines the Anthropic `llm_config` and the Researcher system prompt template. |
| `app/anthropic_compat.py` | **Required shim** — see Conventions. |
| `app/workflow.py` | `run_research(question, *, fields, extra_journals, min_year)`. |
| `app/persistence.py` | Writes the JSON + Markdown reports. |
| `app/server.py` | FastAPI app: `POST /research`, `GET /journals`, `GET /config`, `GET /health`. |
| `app/static/index.html` | The whole web UI — one file, vanilla JS, no build step. |
| `tests/` | 334 offline tests. No network, no API key. |
| `scripts/smoke_test.py` | Live pre-flight checks (real OpenAlex search + one real Claude call). |
| `scripts/validate_journals.py` | Live check that every allowlist entry matches a real OpenAlex source. Run by hand after editing `journals.py`. |

## Conventions & gotchas (read before editing)

- **Claude model is `claude-opus-4-8`.** Use the exact ID; don't downgrade.
- **Do NOT send `temperature`/`top_p`/`top_k` to Claude.** Opus 4.7/4.8/Fable
  reject them with a 400. AG2 injects `temperature=1.0` by default, so
  `app/anthropic_compat.py` patches AG2's `load_config` to strip those params for
  affected models. **Keep this shim** and keep `patch_ag2_anthropic_sampling()`
  called in `agents.py`. If Claude calls start 400-ing on sampling params, that
  patch is the place to look — and `tests/test_anthropic_compat.py` pins the
  AG2 internal it depends on, so an upgrade that breaks it fails the build.
- **AG2 is pinned `<1.0`.** ag2 1.0 renamed the top-level package `autogen` →
  `ag2`, so every `import autogen` in `app/` breaks against it. Don't lift the
  bound without migrating those imports and re-checking the `load_config`
  patch. CI caught this because the old `>=0.7` floor let a fresh install
  resolve 1.0.
- **Keep the data source behind `OpenAlexClient`.** `journals.py`, `filters.py`,
  `tools.py`, `agents.py`, `workflow.py`, `persistence.py` all depend only on the
  `Paper` dataclass — preserve it when changing APIs.
- **High-impact policy** changes go in `journals.py` only. The web UI builds its
  checkboxes from `GET /journals`, so adding a field there needs no UI change —
  but it does need an entry in both `JOURNALS_BY_FIELD` and `FIELD_LABELS`
  (a test enforces that they stay in sync).
- **Journal matching is exact after normalization, not substring.** `"dairy
  science"` will never match *Journal of Dairy Science*. Add the full lowercase
  title, and use `ALIASES` for abbreviations and leading-article variants. Run
  `python -m scripts.validate_journals` after editing — OpenAlex's spelling is
  often not the obvious one (*The* ISME Journal, *Cellular and Molecular*
  Immunology), and a wrong entry fails silently forever.
- **Don't add year-stamped venues.** OpenAlex indexes CVPR as `2022 IEEE/CVF
  Conference on...`; a fixed entry can never match. They are absent on purpose.
- **`FIELD_GROUPS` must partition `JOURNALS_BY_FIELD` exactly** — every key in
  exactly one group. `FIELD_ALIASES` maps retired keys (e.g. `cs_ai`) to their
  replacements so saved selections keep working; don't delete entries from it.
- **`no_abstract` is not `not_found`.** In `verification.py`, a quote that
  cannot be checked because OpenAlex has no abstract must never be reported as
  fabricated, and must not make a report un-ok. Crying wolf trains the reader to
  ignore the real warnings.
- **OpenAlex ids come in two forms.** Papers are keyed by full URL
  (`https://openalex.org/W123`); the model cites the bare `W123`. Always compare
  via `verification.bare_id()` — the direct comparison matches nothing and
  reports every citation as unverified.
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
`OpenAlexClient(session=...)` and `ResearchTools(client=...)` — don't remove
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
