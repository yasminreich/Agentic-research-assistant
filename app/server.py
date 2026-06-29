"""FastAPI backend exposing the research assistant over HTTP."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .workflow import ConfigurationError, run_research

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Automated Research Assistant",
    description="Multi-agent literature review over the Paperclip database.",
    version="0.1.0",
)


class ResearchRequest(BaseModel):
    question: str = Field(..., min_length=3, description="The research question to answer.")


class ResearchResponse(BaseModel):
    question: str
    summary: str
    paper_count: int
    saved: bool
    json_path: str | None = None
    markdown_path: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/research", response_model=ResearchResponse)
def research(request: ResearchRequest) -> ResearchResponse:
    """Run the multi-agent literature review for a research question.

    This is a synchronous, potentially long-running call (the agents make
    several LLM and API round-trips). FastAPI runs it in a worker thread.
    """
    try:
        result = run_research(request.question)
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface any failure to the caller
        logging.exception("Research run failed")
        raise HTTPException(status_code=500, detail=f"Research run failed: {exc}") from exc

    return ResearchResponse(**result)
