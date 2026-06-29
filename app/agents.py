"""Construct the two-agent AG2 team and wire up the tools.

  - Researcher (AssistantAgent, Claude): plans searches, judges relevance,
    clusters same-conclusion papers, writes the summary, calls the save tool.
  - Proxy (UserProxyAgent): executes the registered tool functions. No human
    input; terminates when the Researcher emits TERMINATE.
"""

from __future__ import annotations

from typing import Annotated

from autogen import AssistantAgent, UserProxyAgent, register_function

from .anthropic_compat import patch_ag2_anthropic_sampling
from .config import Settings, get_settings
from .tools import ResearchTools

# Ensure AG2 doesn't send sampling params that Opus 4.7/4.8/Fable reject.
patch_ag2_anthropic_sampling()

TERMINATION_TOKEN = "TERMINATE"

RESEARCHER_SYSTEM_PROMPT = f"""\
You are a meticulous research scientist conducting an automated literature review.

You have access to two tools, executed for you by a proxy:
  - `search_literature(query, year_from, limit)`: searches a literature database
    that has ALREADY been filtered to high-impact, reputable journals and
    deduplicated so that only the most recent paper survives among near-identical
    works. It returns curated candidate papers with their `paper_id`.
  - `save_research_report(summary, paper_ids, question)`: saves your final
    scientific summary and the selected papers to disk.

Follow this process:
1. Decompose the user's research question into 2-4 focused search queries that
   cover its key facets. Call `search_literature` for each (you may call it
   multiple times, refining queries based on what you find).
2. Read the returned papers. Select the ones that genuinely help answer the
   question. The database already targets high-impact journals, so focus on
   relevance and quality.
3. When several papers reach the SAME conclusion, keep the most recent one and
   drop the older redundant ones from your selection.
4. Write a comprehensive, well-structured scientific summary that directly
   answers the research question. Ground every claim in the selected papers,
   note agreement and disagreement between studies, and acknowledge gaps or
   limitations.
5. Call `save_research_report` exactly once with your summary, the `paper_id`
   values of your selected papers, and the original question.
6. After the report is saved, reply with a single final line containing only:
   {TERMINATION_TOKEN}

Be rigorous and concise. Do not fabricate papers, findings, or citations — use
only what the tools return.
"""


def build_team(question: str, settings: Settings | None = None):
    """Create the Researcher + Proxy agents wired to a fresh tool set.

    Returns `(researcher, proxy, tools)`.
    """
    settings = settings or get_settings()

    llm_config = {
        "config_list": [
            {
                "api_type": "anthropic",
                "model": settings.claude_model,
                "api_key": settings.anthropic_api_key,
                "max_tokens": settings.max_tokens,
            }
        ],
        # Disable AG2's response cache so each run hits the API fresh.
        "cache_seed": None,
    }

    researcher = AssistantAgent(
        name="Researcher",
        system_message=RESEARCHER_SYSTEM_PROMPT,
        llm_config=llm_config,
    )

    proxy = UserProxyAgent(
        name="Proxy",
        human_input_mode="NEVER",
        code_execution_config=False,
        is_termination_msg=lambda m: TERMINATION_TOKEN in (m.get("content") or ""),
        max_consecutive_auto_reply=settings.max_agent_turns,
        default_auto_reply="",
    )

    tools = ResearchTools(question=question, settings=settings)

    # AG2's register_function only accepts plain functions (not bound methods),
    # and derives each tool's JSON schema from the wrapper's annotated signature.
    # These thin closures delegate to the per-run `tools` instance.
    def search_literature(
        query: Annotated[str, "Free-text search query for the literature database."],
        year_from: Annotated[
            int | None,
            "Only include papers published in this year or later. Defaults to the configured minimum year.",
        ] = None,
        limit: Annotated[
            int | None,
            "Maximum number of papers to retrieve for this query (capped at 100).",
        ] = None,
    ) -> str:
        return tools.search_literature(query, year_from=year_from, limit=limit)

    def save_research_report(
        summary: Annotated[
            str, "The comprehensive scientific summary answering the research question."
        ],
        paper_ids: Annotated[
            list[str], "The paper_id values of the relevant papers to include in the report."
        ],
        question: Annotated[str, "The original research question being answered."] = "",
    ) -> str:
        return tools.save_research_report(summary, paper_ids, question)

    register_function(
        search_literature,
        caller=researcher,
        executor=proxy,
        name="search_literature",
        description=(
            "Search the high-impact literature database and return curated, "
            "deduplicated candidate papers (with paper_id) relevant to a query."
        ),
    )
    register_function(
        save_research_report,
        caller=researcher,
        executor=proxy,
        name="save_research_report",
        description=(
            "Save the final scientific summary and the selected papers (by "
            "paper_id) to disk. Call this exactly once when the review is complete."
        ),
    )

    return researcher, proxy, tools
