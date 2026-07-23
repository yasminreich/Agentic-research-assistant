"""FastAPI backend + web UI for the research assistant."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .limits import DailyRunLimiter
from .workflow import ConfigurationError, run_research

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Automated Research Assistant",
    description="Multi-agent literature review over the Paperclip database.",
    version="0.1.0",
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Per-day run cap shared across requests (see app/limits.py for the caveats).
_settings = get_settings()
_run_limiter = DailyRunLimiter(_settings.max_runs_per_day)


class ResearchRequest(BaseModel):
    question: str = Field(..., min_length=3, description="The research question to answer.")


class ResearchResponse(BaseModel):
    question: str
    summary: str
    paper_count: int
    saved: bool
    papers: list[dict] = []
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
    """UI hints. `password_required` lets the page hide the password field when
    no `ACCESS_PASSWORD` is configured."""
    return {"password_required": bool(get_settings().access_password)}


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

    # 3. Daily run cap (bounds worst-case cost). Reserve a slot up front and give
    #    it back if the run fails so crashes don't count against the cap.
    if not _run_limiter.try_acquire():
        raise HTTPException(
            status_code=429,
            detail="Daily research limit reached. Please try again tomorrow.",
        )

    try:
        result = run_research(question)
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
