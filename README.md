# Research Assistant

[![CI](https://github.com/yasminreich/Agentic-research-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/yasminreich/Agentic-research-assistant/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

Ask a research question in your browser and get a clear, cited summary of the
scientific literature — written by AI agents that search real papers and focus on
high-impact journals.

![The Advanced options panel: an earliest-year field and checkboxes for 24 journal fields grouped into Life sciences, Physical sciences, Computing and Social sciences, with Medicine, Microbiome and Immunology checked.](docs/screenshots/form.png)

Ask a question, pick the fields it belongs to, and get a grounded summary:

![The rendered result: a Summary card answering the question.](docs/screenshots/result.png)

…followed by every paper it drew on, with journal, year, citation count and a
resolvable DOI:

![The selected-papers list: five papers from Journal of Dairy Science, Journal of Animal Science and animal, each with a DOI link.](docs/screenshots/papers.png)

**[→ Read a full report end to end](docs/example-report.md)** — 25 papers, every
citation resolvable. Nothing in it was written by hand.

## How it works

Two AI agents (built on the AG2 / AutoGen framework) work together on each question:

- **Researcher agent** — powered by Claude. It plans a few search queries, judges
  which returned papers are actually relevant, groups papers that reach the same
  conclusion (keeping the most recent), and writes the final cited summary.
- **Proxy agent** — runs the searches the Researcher asks for, against
  **OpenAlex**, a free and open catalogue of scientific papers.

Results are filtered to a curated list of **high-impact journals**, **deduplicated
by recency** (when several papers agree, the most recent one wins), and saved to the
`output/` folder as JSON and Markdown.

```
You ask a question
   → Researcher plans a few search queries
   → Proxy searches OpenAlex for real papers
        → filtered to the journal fields you chose
        → near-duplicate papers collapsed, most recent kept
   → Researcher judges relevance and writes a cited summary
   → the report is saved to output/<timestamp>-<slug>.json + .md
```

The deterministic parts (searching, the journal allowlist, deduplication) are plain
Python so they're auditable; the judgment calls (relevance, "same conclusion") are
the Researcher's.

## Quick start

You need **Python 3.10+** and an **Anthropic API key** (from
[console.anthropic.com](https://console.anthropic.com/)). Paper search uses
[OpenAlex](https://openalex.org/), which is free and needs no key.

```bash
# 1. Install the dependencies
pip install -r requirements.txt

# 2. Add your API key
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
# then open .env and set:  ANTHROPIC_API_KEY=sk-ant-...

# 3. Start it
python run.py
```

Now open **http://localhost:8000**, type a question, and click **Run literature
review**. A run takes about 1–2 minutes. That's it. 🎉

Each run also saves a full report (summary + every paper) to the `output/` folder
as JSON and Markdown.

## Choosing which journals count

This is the setting that most affects your results. Open **Advanced options** on
the page.

The allowlist covers **255 journals across 24 fields**, grouped into sections. By
default all of them are searched, which is usually not what you want — a question
about the gut microbiome returns better papers when you narrow to *Microbiome* and
*Immunology* than when *Physics* and *Law* are competing for the same slots.

| Group | Fields |
|---|---|
| **Life sciences** | Medicine & clinical · Biology & genetics · Microbiome & microbiology · Immunology · Bioinformatics · Neuroscience · Public health · Agriculture & food · Ecology & evolution |
| **Physical sciences** | Chemistry · Physics & astronomy · Materials & engineering · Earth & environment |
| **Computing** | AI & machine learning · Computer science · Security & privacy · Statistics & data science · Robotics · Human-computer interaction |
| **Social sciences** | Psychology & behaviour · Economics & social science · Education · Law & policy |
| **General** | Multidisciplinary |

Three controls:

- **Fields to search** — check the disciplines your question belongs to.
- **Also accept these journals** — for venues the list doesn't cover. Separate
  several with **new lines, commas or semicolons**:
  ```
  Gut Microbes, mSystems; The ISME Journal
  ```

  ![The "Also accept these journals" box containing "Gut Microbes, mSystems; The ISME Journal" on one line.](docs/screenshots/custom-journals.png)

  Use the title exactly as it appears on the paper (*Journal of Dairy Science*,
  not *Dairy Science*) — matching is exact, not by keyword. One exception: a
  journal whose own title contains a comma (*Annual Review of Ecology, Evolution,
  and Systematics*) needs its own line.
- **Earliest publication year** — defaults to `MIN_YEAR` from your `.env`.

**Got no papers back?** The page lists the journals your filter excluded, with
counts. Paste the ones you trust into the custom box and run again. That list is
almost always the answer — the venue filter is a far more common cause of an
empty result than a genuine absence of literature.

**Named a journal and saw nothing from it?** The page says so explicitly, under
*"No papers came from these journals"*. That almost always means a spelling
mismatch rather than an absence of papers.

### Why some journals are deliberately missing

*Frontiers in …*, *Nutrients*, *IJMS* and *Scientific Reports* are peer-reviewed
but not selective, and including them would defeat the point of a quality filter.
They show up in the excluded list every run, so you can add them by name whenever
you want them.

A few conference venues can't be listed at all: OpenAlex indexes CVPR as
`2022 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)` and
ACM CCS similarly, and a fixed entry can never match a name that changes every
year.

To change the allowlist permanently, edit `JOURNALS_BY_FIELD` in
[`app/journals.py`](app/journals.py) — the single source of truth, which the web
page reads via `GET /journals`. Then check your additions really match:

```bash
python -m scripts.validate_journals            # or one field, e.g. microbiome
```

## How do I know it isn't making things up?

Partly you're told, and partly it's checked for you. The honest split:

| | Written by | Can it be invented? |
|---|---|---|
| The papers in the list | OpenAlex | **No.** The model can only pick from what a search returned; an id it invents is dropped and reported. |
| Titles, journals, years, DOIs | OpenAlex | **No.** Rendered straight from the API record. |
| The summary text | Claude | **Yes** — it's a synthesis, and that's what the checks below are for. |

Every run is audited mechanically — no model grading another model — and the
result appears above the summary:

```
✓ 24 of 24 citations in the summary match papers this run retrieved.
✓ 11 of 12 supporting quotes were found in the cited paper's abstract.
ℹ 1 quote could not be checked — OpenAlex has no abstract for that paper.
  This is not a sign of a problem.
```

Two things are checked:

1. **Every citation is real.** The Researcher cites papers inline by id. Each one
   is matched against the papers a search actually returned this run. An id that
   was never returned is flagged by name.
2. **Every quote is real.** For its main claims the Researcher must supply a
   quote copied from that paper's abstract. Each is checked against the *full*
   abstract — the model only ever saw a truncated preview, so an invented quote
   has nowhere to hide. Quotes appear under each paper, tagged verified or not.

**"Could not be checked" is not an accusation.** OpenAlex has no abstract for
many records. Those are reported as uncheckable and nothing more — crying wolf
there would just teach you to ignore the warnings.

### What this still doesn't prove

That a real quote from a real paper actually *supports* the argument built on it.
That's a reading, not a string comparison, and no automated check settles it.
This is why every paper is listed with a resolvable DOI: for anything you intend
to rely on, open the paper.

Treat a report as a well-organised, verifiable starting point — not as a
peer-reviewed conclusion.

## Share it with others

Want other people to try it from a link — no install, no key on their end? Deploy
it once and share the URL. It runs on **your** API key, so cap your spending first.

**→ [Full step-by-step guide](docs/deploying.md)**, including what to warn people
about and how to rotate the key or take it down. The short version:

1. **Set a spend limit** at [console.anthropic.com](https://console.anthropic.com/)
   → Settings → Limits (e.g. $15/month). This is your safety net — a run costs
   roughly **$0.15–$1.00**.
2. **Deploy to [Render](https://render.com/)** (free tier): sign in with GitHub →
   **New + → Blueprint** → pick this repo → set `ANTHROPIC_API_KEY` → **Apply**.
   You get a public URL in a few minutes. (The included `Dockerfile` and
   `render.yaml` do the setup; Railway and Fly.io work the same way.)
3. **Share the URL.** Optionally set `ACCESS_PASSWORD` so only people you give the
   password to can use it.

## Common settings

Everything is configured in `.env` (see `.env.example`). The only **required**
value is `ANTHROPIC_API_KEY`. The handy optional ones:

| Setting | Default | What it does |
|---|---|---|
| `ACCESS_PASSWORD` | *(blank)* | Password for the web page. Blank = anyone with the link can use it. |
| `MAX_RUNS_PER_DAY` | `50` | Daily cap on runs — bounds your cost. |
| `MIN_YEAR` | `2015` | Default earliest year (overridable per run in the UI). |
| `MAX_PAPERS_PER_QUERY` | `50` | Papers fetched per search. |

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt

pytest                  # 334 tests, no network and no API key needed
ruff check . && ruff format --check .
```

The suite is entirely offline — `OpenAlexClient` takes an injected
`requests.Session` and `ResearchTools` takes an injected client, so nothing in
`tests/` makes a real call or spends money. CI runs the same three commands on
Python 3.10, 3.11 and 3.12.

The live checks are separate and deliberately manual:

```bash
python -m scripts.smoke_test    # one real OpenAlex search + one real Claude call
```

## Limitations

Worth knowing before you rely on it:

- **The allowlist is curated and finite.** 255 journals is a deliberate quality
  filter, not full coverage of the literature. Good papers in smaller or newer
  venues are excluded unless you name them. The excluded-journals list on each run
  tells you what you're missing.
- **OpenAlex is free but metered.** Paper search needs no key, but there is a
  daily request budget. A heavy day exhausts it and runs fail with a message
  saying it resets at midnight UTC. Setting `OPENALEX_MAILTO` gets you the
  politer, faster pool.
- **A run is a single blocking request** of 1–2 minutes. There's no job queue and
  no progress streaming; the page waits with a 3-minute timeout. On Render's free
  tier a cold start eats into that.
- **The daily run cap is per-process and in-memory.** It resets on restart or
  redeploy, and multiple workers each keep their own count. Your real spending
  guarantee is the Anthropic Console limit — set that too.
- **The summary is the model's synthesis.** Every paper it cites is real and
  resolvable, and its citations and quotes are checked automatically — but
  whether a quote actually supports the argument built on it is a reading, and
  that stays your job. See [above](#how-do-i-know-it-isnt-making-things-up).

## API

The web page is a front end for one endpoint. You can call it directly:

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{
        "question": "Does colostrum fat composition affect calf immune development?",
        "fields": ["agriculture_food", "medicine"],
        "min_year": 2018
      }'
```

On Windows PowerShell use `Invoke-RestMethod`.

| Endpoint | Purpose |
|---|---|
| `POST /research` | Run a review. Body: `question`, optional `fields`, `extra_journals`, `min_year`. Header `X-Access-Password` when a password is set. |
| `GET /journals` | The field list, grouped, with labels and journal counts. |
| `GET /config` | UI hints: whether a password is required, `min_year`, `max_question_chars`. |
| `GET /health` | Liveness check. |

Interactive docs are at `/docs` once the server is running.

`fields` has three meanings: omitted or `null` searches every field; a list
searches those fields; an **empty list** searches no field, so only
`extra_journals` applies. A request with neither is rejected — it could only ever
return nothing.

<details>
<summary><b>More details</b></summary>

### All settings

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Claude access for the Researcher. |
| `OPENALEX_MAILTO` | — | Optional; your email for OpenAlex's faster "polite pool". |
| `CLAUDE_MODEL` | `claude-opus-4-8` | Model for the Researcher. Check current model IDs before changing. |
| `MIN_YEAR` | `2015` | Default earliest publication year. |
| `MAX_PAPERS_PER_QUERY` | `50` | Results requested per query (the API caps at 200). |
| `MAX_AGENT_TURNS` | `15` | Safety cap on automatic agent turns per run. |
| `OUTPUT_DIR` | `output` | Where reports are written. |
| `ACCESS_PASSWORD` | — | Shared password for the web UI. Blank = no gate. |
| `MAX_RUNS_PER_DAY` | `50` | In-app cap on runs per day (UTC). |
| `MAX_QUESTION_CHARS` | `500` | Reject questions longer than this. |

### Project layout

```
app/
  config.py            # settings (pydantic-settings)
  openalex_client.py   # OpenAlex Works API client
  journals.py          # journal fields, allowlist, JournalPolicy
  filters.py           # policy filter, recency dedup, excluded-journal counts
  verification.py      # citation + quote checks on what the model wrote
  tools.py             # search / save tools the agents call
  agents.py            # Researcher + Proxy agents
  workflow.py          # run_research() orchestration
  persistence.py       # JSON + Markdown report writer
  server.py            # FastAPI app: web page + /research + /journals + /health
  limits.py            # in-memory per-day run cap
  static/index.html    # the web page (served at /)
tests/                 # 334 offline tests
scripts/
  smoke_test.py        # live pre-flight checks
  validate_journals.py # check the allowlist against OpenAlex
run.py                 # launcher
Dockerfile, render.yaml  # deployment
```

### Troubleshooting

**"No papers matched your journal filter."** Open Advanced options and check more
fields, or paste the excluded journal names the page shows you into *Also accept
these journals*.

**`400` error about `temperature` from Claude.** Opus 4.8 rejects sampling
parameters, which AG2 sends by default. This is handled automatically by
`app/anthropic_compat.py`. If Claude calls start failing this way after an AG2
upgrade, that shim is where to look — `tests/test_anthropic_compat.py` pins the
assumption it relies on.

**"OpenAlex's free daily request budget is exhausted."** OpenAlex meters usage
and the day's free allowance is gone. It resets at midnight UTC; nothing else
recovers it. Setting `OPENALEX_MAILTO` moves you into the politer, faster pool.

**OpenAlex `429` (ordinary rate limit).** Rare, and the client retries
automatically.

</details>

## License

MIT — see [LICENSE](LICENSE).
