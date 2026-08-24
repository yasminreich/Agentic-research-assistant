"""FastAPI backend + web UI for the research assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .journals import FIELD_GROUPS, FIELD_LABELS, JOURNALS_BY_FIELD
from .limits import DailyRunLimiter
from .workflow import ConfigurationError, run_research

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Automated Research Assistant",
    description="Multi-agent literature review over OpenAlex.",
    version="0.1.0",
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Per-day run cap shared across requests (see app/limits.py for the caveats).
_settings = get_settings()
_run_limiter = DailyRunLimiter(_settings.max_runs_per_day)


# Guardrails on the per-run journal controls. A caller cannot make the search
# unboundedly expensive or ask for papers from the future.
MAX_EXTRA_JOURNALS = 50
MAX_JOURNAL_NAME_CHARS = 200
EARLIEST_YEAR = 1900


class ResearchRequest(BaseModel):
    question: str = Field(..., min_length=3, description="The research question to answer.")
    fields: list[str] | None = Field(
        default=None,
        description=(
            "Journal field keys to search (see GET /journals). "
            "Omit or leave empty to search every field."
        ),
    )
    extra_journals: list[str] | None = Field(
        default=None,
        description="Additional journal titles to accept, on top of `fields`.",
    )
    min_year: int | None = Field(
        default=None,
        description="Earliest publication year. Defaults to the configured MIN_YEAR.",
    )


class ResearchResponse(BaseModel):
    question: str
    summary: str
    paper_count: int
    saved: bool
    papers: list[dict] = []
    # Journals the run's filter turned away, most frequent first. Lets the UI
    # explain an empty result instead of just showing nothing.
    rejected_journals: list[dict] = []
    # Journals the caller named that no paper came from — usually a typo.
    unmatched_journals: list[str] = []
    # Mechanical checks on the summary: are its citations real, and do its
    # quotes appear in the abstracts they are attributed to?
    verification: dict = {}
    json_path: str | None = None
    markdown_path: str | None = None


@app.get("/")
def index() -> FileResponse:
    """Serve the tester-facing web page."""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/config")
def config() -> dict:
    """UI hints, so the page does not hardcode server-side limits."""
    settings = get_settings()
    return {
        "password_required": bool(settings.access_password),
        "min_year": settings.min_year,
        "max_question_chars": settings.max_question_chars,
        "earliest_year": EARLIEST_YEAR,
    }


@app.get("/journals")
def journals() -> dict:
    """The journal fields a caller can choose from.

    The web page renders its checkboxes from this, so the field list lives in
    `app/journals.py` only and the UI never carries a stale copy.
    """
    return {
        # Grouped so the page can render readable sections rather than two
        # dozen undifferentiated checkboxes. Order here is the display order.
        "groups": [
            {
                "name": group,
                "fields": [
                    {
                        "key": key,
                        "label": FIELD_LABELS.get(key, key),
                        "count": len(JOURNALS_BY_FIELD[key]),
                        "examples": sorted(JOURNALS_BY_FIELD[key])[:3],
                    }
                    for key in keys
                ],
            }
            for group, keys in FIELD_GROUPS.items()
        ],
        "total_fields": len(JOURNALS_BY_FIELD),
        "total_journals": len(set().union(*JOURNALS_BY_FIELD.values())),
    }


@app.post("/research", response_model=ResearchResponse)
def research(
    request: ResearchRequest,
    x_access_password: str | None = Header(default=None),
) -> ResearchResponse:
    """Run the multi-agent literature review for a research question.

    This is a synchronous, potentially long-running call (the agents make
    several LLM and API round-trips). FastAPI runs it in a worker thread.
    """
    settings = get_settings()

    # 1. Access gate: if a password is configured, the caller must supply it.
    if settings.access_password and x_access_password != settings.access_password:
        raise HTTPException(status_code=401, detail="Invalid or missing access password.")

    # 2. Question length guard.
    question = request.question.strip()
    if len(question) > settings.max_question_chars:
        raise HTTPException(
            status_code=422,
            detail=f"Question is too long (max {settings.max_question_chars} characters).",
        )

    # 3. Journal / year controls. Validated here so a bad request is rejected
    #    before it can reserve a run slot or reach the API.
    min_year = request.min_year
    if min_year is not None:
        this_year = datetime.now(timezone.utc).year
        if not EARLIEST_YEAR <= min_year <= this_year:
            raise HTTPException(
                status_code=422,
                detail=f"min_year must be between {EARLIEST_YEAR} and {this_year}.",
            )

    extra_journals = [j.strip() for j in (request.extra_journals or []) if j.strip()]
    if request.fields is not None and not request.fields and not extra_journals:
        raise HTTPException(
            status_code=422,
            detail=(
                "No journals selected. Check at least one field, or name a journal "
                "under 'Also accept these journals'."
            ),
        )
    if len(extra_journals) > MAX_EXTRA_JOURNALS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_EXTRA_JOURNALS} extra journals may be supplied.",
        )
    if any(len(j) > MAX_JOURNAL_NAME_CHARS for j in extra_journals):
        raise HTTPException(
            status_code=422,
            detail=f"Journal names must be at most {MAX_JOURNAL_NAME_CHARS} characters.",
        )

    # 4. Daily run cap (bounds worst-case cost). Reserve a slot up front and give
    #    it back if the run fails so crashes don't count against the cap.
    if not _run_limiter.try_acquire():
        raise HTTPException(
            status_code=429,
            detail="Daily research limit reached. Please try again tomorrow.",
        )

    try:
        result = run_research(
            question,
            fields=request.fields,
            extra_journals=extra_journals,
            min_year=min_year,
        )
    except ConfigurationError as exc:
        _run_limiter.release()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        _run_limiter.release()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface any failure to the caller
        _run_limiter.release()
        logging.exception("Research run failed")
        raise HTTPException(status_code=500, detail=f"Research run failed: {exc}") from exc

    return ResearchResponse(**result)
