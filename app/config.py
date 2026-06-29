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


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
