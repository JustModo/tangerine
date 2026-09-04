import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.graphs.shared import attempt, cached_generate, route, run_graph
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.prompts.problem import (
    adapt_problem_user_prompt,
    patch_problem_user_prompt,
    patch_system_prompt,
    problem_system_prompt,
    problem_user_prompt,
)
from app.llm.schemas.problem import GeneratedProblem, ProblemPatch

logger = logging.getLogger(__name__)


class ProblemGraphState(TypedDict):
    skill: str
    language: str
    difficulty: str
    source_problem: str | None
    avoid_titles: list[str]
    result: GeneratedProblem | None
    error: str | None
    attempts: int


def build_problem_graph(provider: LLMProvider):
    async def generate(state: ProblemGraphState) -> ProblemGraphState:
        return await attempt(provider, state, problem_system_prompt(state["language"]), (
                adapt_problem_user_prompt(state["source_problem"], state["language"])
                if state["source_problem"]
                else problem_user_prompt(
                    state["skill"],
                    state["language"],
                    state["difficulty"],
                    state["avoid_titles"],
                )
            ), GeneratedProblem)

    graph = StateGraph(ProblemGraphState)
    graph.add_node("generate", generate)
    graph.set_entry_point("generate")
    graph.add_conditional_edges("generate", route, {"retry": "generate", "done": END})
    return graph.compile()


async def generate_problem(
    provider: LLMProvider,
    skill: str,
    language: str,
    difficulty: str,
    cache: SqliteLLMCache | None = None,
    source_problem: str | None = None,
    avoid_titles: list[str] | None = None,
) -> GeneratedProblem:
    # Pasted problems not cached; avoid_titles part of key (not just prompt).
    return await cached_generate(
        cache,
        None
        if source_problem
        else ["problem", skill, language, difficulty, *sorted(avoid_titles or [])],
        GeneratedProblem,
        lambda: run_graph(
            build_problem_graph(provider),
            {
                "skill": skill,
                "language": language,
                "difficulty": difficulty,
                "source_problem": source_problem,
                "avoid_titles": avoid_titles or [],
            },
            "Problem generation",
        ),
    )


async def patch_problem(
    provider: LLMProvider,
    generated: GeneratedProblem,
    kind: str,
    detail: str,
    language: str,
) -> ProblemPatch | None:
    """One repair attempt for a problem the sandbox just rejected, given what actually
    happened when it ran.

    No graph, no retry, no cache: a patch is a single cheap call that either helps or
    doesn't, and its caller already has a fresh regeneration lined up behind it. Caching
    would be actively wrong — the key would be the same broken problem every time."""
    request = StructuredGenerationRequest(
        # The repair subset of the generation prompt, so the rules a patch must honour
        # cannot drift from the ones that produced the problem.
        system_prompt=patch_system_prompt(language),
        user_prompt=patch_problem_user_prompt(kind, detail, language, generated),
    )
    try:
        return await provider.generate_structured(request, ProblemPatch)
    except SchemaValidationError:
        # Parse failure means regenerate (repair isn't salvageable).
        logger.warning("Problem patch failed to parse (kind=%s)", kind)
        return None
