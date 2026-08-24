import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.infrastructure.cache import SqliteLLMCache, cache_key
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.prompts.problem import (
    PROBLEM_SYSTEM_PROMPT,
    adapt_problem_user_prompt,
    patch_problem_user_prompt,
    problem_user_prompt,
)
from app.llm.schemas.problem import GeneratedProblem, ProblemPatch

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


class ProblemGraphState(TypedDict):
    skill: str
    language: str
    difficulty: str
    # Adapt from this pasted statement instead of inventing.
    source_problem: str | None
    # Titles already in the bank (don't repeat).
    avoid_titles: list[str]
    result: GeneratedProblem | None
    error: str | None
    attempts: int


def build_problem_graph(provider: LLMProvider):
    async def generate(state: ProblemGraphState) -> ProblemGraphState:
        request = StructuredGenerationRequest(
            system_prompt=PROBLEM_SYSTEM_PROMPT,
            user_prompt=(
                adapt_problem_user_prompt(state["source_problem"], state["language"])
                if state["source_problem"]
                else problem_user_prompt(
                    state["skill"],
                    state["language"],
                    state["difficulty"],
                    state["avoid_titles"],
                )
            ),
        )
        try:
            result = await provider.generate_structured(request, GeneratedProblem)
            return {**state, "result": result, "error": None}
        except SchemaValidationError as exc:
            return {**state, "error": str(exc), "attempts": state["attempts"] + 1}

    def route(state: ProblemGraphState) -> str:
        if state["result"] is not None or state["attempts"] >= MAX_ATTEMPTS:
            return "done"
        return "retry"

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
    key = (
        cache_key("problem", skill, language, difficulty, *sorted(avoid_titles or []))
        if cache is not None and not source_problem
        else None
    )
    if cache is not None and key is not None:
        cached = await cache.get(key)
        if cached is not None:
            return GeneratedProblem.model_validate_json(cached)

    graph = build_problem_graph(provider)
    final_state = await graph.ainvoke(
        {
            "skill": skill,
            "language": language,
            "difficulty": difficulty,
            "source_problem": source_problem,
            "avoid_titles": avoid_titles or [],
            "result": None,
            "error": None,
            "attempts": 0,
        }
    )
    if final_state["result"] is None:
        raise SchemaValidationError(
            f"Problem generation failed after {MAX_ATTEMPTS} attempts: {final_state['error']}"
        )

    if cache is not None and key is not None:
        await cache.set(key, final_state["result"].model_dump_json())

    return final_state["result"]


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
    needs_statement = kind == "mismatch"
    request = StructuredGenerationRequest(
        # Reuse system prompt to avoid drift between generation and repair.
        system_prompt=PROBLEM_SYSTEM_PROMPT,
        user_prompt=patch_problem_user_prompt(
            kind=kind,
            detail=detail,
            language=language,
            pre_code=generated.pre_code,
            reference_user_code=generated.reference_user_code,
            post_code=generated.post_code,
            examples=generated.examples,
            hidden_tests=generated.hidden_tests,
            statement_md=generated.statement_md if needs_statement else None,
            # Stub only relevant for no_tests repairs (format must match).
            user_code=generated.user_code if kind == "no_tests" else None,
        ),
    )
    try:
        return await provider.generate_structured(request, ProblemPatch)
    except SchemaValidationError:
        # Parse failure means regenerate (repair isn't salvageable).
        logger.warning("Problem patch failed to parse (kind=%s)", kind)
        return None
