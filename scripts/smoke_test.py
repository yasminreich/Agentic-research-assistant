"""Smoke tests that don't run the full agent loop.

Run from the project root:
    python -m scripts.smoke_test

Checks, in order:
  1. OpenAlex search + high-impact filter + dedup. Needs network but
     no API key.
  2. The Claude-through-AG2 path (only if ANTHROPIC_API_KEY is set). This is the
     important one: it confirms AG2's Anthropic client and the configured model
     (default claude-opus-4-8) work together. If AG2 injects an unsupported
     parameter (e.g. temperature/top_p), Opus 4.8 returns HTTP 400 and you'll
     see it here before wiring up the whole workflow.
"""

from __future__ import annotations

import sys

from app.config import get_settings
from app.filters import deduplicate_by_recency, filter_high_impact
from app.openalex_client import OpenAlexClient, OpenAlexError


def check_openalex() -> bool:
    print("== OpenAlex search check ==")
    client = OpenAlexClient()
    try:
        papers = client.search("intermittent fasting insulin sensitivity", limit=20, year_from=2015)
    except OpenAlexError as exc:
        print(f"  FAIL: {exc}")
        return False

    high_impact = filter_high_impact(papers)
    curated = deduplicate_by_recency(high_impact)
    print(f"  retrieved={len(papers)} high_impact={len(high_impact)} curated={len(curated)}")
    for p in curated[:5]:
        print(f"    - [{p.year}] {p.journal_name}: {p.title[:70]}")
    print("  OK")
    return True


def check_llm() -> bool:
    settings = get_settings()
    print("== Claude-through-AG2 check ==")
    if not settings.anthropic_api_key:
        print("  SKIP: ANTHROPIC_API_KEY not set.")
        return True

    from autogen import AssistantAgent

    llm_config = {
        "config_list": [
            {
                "api_type": "anthropic",
                "model": settings.claude_model,
                "api_key": settings.anthropic_api_key,
                "max_tokens": 64,
            }
        ],
        "cache_seed": None,
    }
    agent = AssistantAgent(name="SmokeTester", llm_config=llm_config)
    try:
        reply = agent.generate_reply(
            messages=[{"role": "user", "content": "Reply with exactly: OK"}]
        )
    except Exception as exc:  # noqa: BLE001 - we want to see the raw error
        print(f"  FAIL ({settings.claude_model}): {type(exc).__name__}: {exc}")
        print(
            "  If this is a 400 about temperature/top_p, AG2 is sending a "
            "parameter Opus 4.8 rejects. See README troubleshooting."
        )
        return False

    print(f"  model={settings.claude_model} reply={reply!r}")
    print("  OK")
    return True


def main() -> int:
    ok = check_openalex()
    ok = check_llm() and ok
    print("\nALL PASSED" if ok else "\nSOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
