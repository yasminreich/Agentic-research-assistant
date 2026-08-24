"""Client for the OpenAlex Works API (https://api.openalex.org/works).

OpenAlex is a free, open catalogue of scholarly works and needs no API key.

This module is the single place that knows about the upstream wire format.
Everything else in the app works with the normalized `Paper` dataclass below,
so swapping the data source means rewriting only this file — keep `Paper` and
the `search()` signature stable if you do.

Setting an email via `OPENALEX_MAILTO` opts into OpenAlex's faster "polite pool"
(recommended, but not required).
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import asdict, dataclass, field

import requests

from .config import get_settings

logger = logging.getLogger(__name__)

WORKS_ENDPOINT = "https://api.openalex.org/works"

# Fields we ask OpenAlex to return for each work.
WORK_FIELDS = ",".join(
    [
        "id",
        "display_name",
        "publication_year",
        "cited_by_count",
        "primary_location",
        "authorships",
        "doi",
        "abstract_inverted_index",
    ]
)

# OpenAlex caps `per-page` at 200.
MAX_LIMIT = 200

_DOI_PREFIX = "https://doi.org/"


def _is_budget_exhausted(body: str) -> bool:
    """True if a 429 body says the daily budget is spent rather than "slow down"."""
    lowered = (body or "").lower()
    return "insufficient budget" in lowered or (
        "rate limit exceeded" in lowered and "budget" in lowered
    )


@dataclass
class Paper:
    """A normalized literature record, decoupled from the upstream API shape."""

    paper_id: str
    title: str
    abstract: str | None
    year: int | None
    venue: str | None
    journal_name: str | None
    citation_count: int
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class OpenAlexError(RuntimeError):
    """Raised when the OpenAlex API cannot be reached."""


class OpenAlexBudgetExhausted(OpenAlexError):
    """Raised when the day's free OpenAlex request budget is used up.

    OpenAlex meters usage; a busy day exhausts the free allowance and every
    request 429s with an "Insufficient budget" body until it resets at midnight
    UTC. Retrying cannot help, so this is raised immediately rather than after
    the normal backoff sequence.
    """


class OpenAlexClient:
    """Thin, retrying wrapper over the OpenAlex Works API."""

    def __init__(
        self,
        mailto: str | None = None,
        *,
        session: requests.Session | None = None,
        max_retries: int = 4,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self._mailto = mailto if mailto is not None else settings.openalex_mailto
        self._session = session or requests.Session()
        self._max_retries = max_retries
        self._timeout = timeout

    # --- public API ---------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
    ) -> list[Paper]:
        """Search the literature for `query` and return normalized papers.

        Args:
            query: Free-text search query (matches titles, abstracts, fulltext).
            limit: Max results to return (capped at `MAX_LIMIT` by the API).
            year_from: Only include papers published in this year or later.
        """
        filters = ["type:article"]
        if year_from is not None:
            filters.append(f"from_publication_date:{year_from}-01-01")

        params: dict[str, str | int] = {
            "search": query,
            "filter": ",".join(filters),
            "per-page": max(1, min(limit, MAX_LIMIT)),
            "select": WORK_FIELDS,
        }
        if self._mailto:
            params["mailto"] = self._mailto

        payload = self._get(WORKS_ENDPOINT, params)
        records = payload.get("results") or []
        papers = [self._normalize(record) for record in records]
        # Drop records with no usable title.
        return [p for p in papers if p.title]

    # --- internals ----------------------------------------------------------

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"Accept": "application/json"}

    def _get(self, url: str, params: dict) -> dict:
        """GET with exponential backoff on 429 / transient 5xx errors.

        OpenAlex is generous (no key, ~10 req/s in the polite pool) but can still
        429 under load, so backoff is retained.
        """
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    headers=self._headers(),
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:  # network-level failure
                last_error = exc
                self._sleep_backoff(attempt)
                continue

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429 and _is_budget_exhausted(response.text):
                # Not transient: nothing recovers this before the daily reset.
                raise OpenAlexBudgetExhausted(
                    "OpenAlex's free daily request budget is exhausted; it resets at "
                    "midnight UTC. Set OPENALEX_MAILTO to use the politer, faster "
                    "pool, or try again tomorrow."
                )

            if response.status_code == 429 or response.status_code >= 500:
                last_error = OpenAlexError(
                    f"OpenAlex returned {response.status_code}: {response.text[:200]}"
                )
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(int(retry_after), 30))
                else:
                    self._sleep_backoff(attempt)
                continue

            # Non-retryable client error.
            raise OpenAlexError(
                f"OpenAlex request failed ({response.status_code}): {response.text[:200]}"
            )

        raise OpenAlexError(
            f"OpenAlex request failed after {self._max_retries + 1} attempts"
        ) from last_error

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        delay = min(2.0**attempt + random.uniform(0, 1), 30.0)
        logger.debug("Backing off %.1fs (attempt %d)", delay, attempt + 1)
        time.sleep(delay)

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict | None) -> str | None:
        """Rebuild an abstract string from OpenAlex's inverted index.

        OpenAlex returns abstracts as `{word: [positions...]}`. Reassemble by
        placing each word at its position(s). Returns None when absent (common).
        """
        if not inverted_index:
            return None
        positions: list[tuple[int, str]] = []
        for word, idxs in inverted_index.items():
            for i in idxs:
                positions.append((i, word))
        if not positions:
            return None
        positions.sort(key=lambda pair: pair[0])
        return " ".join(word for _, word in positions)

    @classmethod
    def _normalize(cls, record: dict) -> Paper:
        """Convert a raw OpenAlex work record into a `Paper`."""
        primary_location = record.get("primary_location") or {}
        source = primary_location.get("source") or {}
        journal_name = source.get("display_name") if isinstance(source, dict) else None

        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (record.get("authorships") or [])
            if isinstance(a, dict) and (a.get("author") or {}).get("display_name")
        ]

        # OpenAlex DOIs are full URLs (https://doi.org/...); store the bare DOI so
        # persistence can render the link consistently.
        doi = record.get("doi")
        if isinstance(doi, str) and doi.startswith(_DOI_PREFIX):
            doi = doi[len(_DOI_PREFIX) :]

        url = primary_location.get("landing_page_url") or record.get("id")

        return Paper(
            paper_id=record.get("id", ""),
            title=(record.get("display_name") or "").strip(),
            abstract=cls._reconstruct_abstract(record.get("abstract_inverted_index")),
            year=record.get("publication_year"),
            venue=journal_name,
            journal_name=journal_name.strip() if isinstance(journal_name, str) else None,
            citation_count=record.get("cited_by_count") or 0,
            authors=authors,
            doi=doi,
            url=url,
        )
