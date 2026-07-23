"""Application settings, loaded from environment / `.env`."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables (case-insensitive) or a local
    `.env` file. See `.env.example` for the full list.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Credentials ---
    anthropic_api_key: str = ""
    # Optional email for OpenAlex's faster "polite pool". OpenAlex needs no key.
    openalex_mailto: str = ""

    # --- LLM ---
    claude_model: str = "claude-opus-4-8"
    # Max output tokens per Claude turn. Opus 4.8 supports up to 128k (streaming
    # required above ~16k); 8192 is plenty for planning + summaries.
    max_tokens: int = 8192

    # --- Search / filtering ---
    min_year: int = 2015
    max_papers_per_query: int = 50

    # --- Orchestration ---
    max_agent_turns: int = 15

    # --- Output ---
    output_dir: str = "output"

    # --- Web UI / sharing guardrails ---
    # Shared password testers must enter to run a research query. When set, the
    # public UI is usable only by people you give the password to. Blank = no
    # password (fine for local use; set it before exposing a public URL).
    access_password: str = ""
    # Safety cap on total research runs per calendar day (UTC), across all users.
    # Bounds worst-case daily API cost. The real hard cap is the Anthropic
    # Console monthly spend limit; this is a lighter in-app backstop.
    max_runs_per_day: int = 50
    # Reject questions longer than this many characters (avoids giant inputs).
    max_question_chars: int = 500


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
