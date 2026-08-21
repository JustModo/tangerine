from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.infrastructure.cache import SqliteLLMCache, cache_key
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.prompts.problem import (
    PROBLEM_SYSTEM_PROMPT,
    adapt_problem_user_prompt,
    problem_user_prompt,
)
from app.llm.schemas.problem import GeneratedProblem

MAX_ATTEMPTS = 3


class ProblemGraphState(TypedDict):
    skill: str
    language: str
    difficulty: str
    # When set, the problem is adapted from this exact pasted statement instead of invented.
    source_problem: str | None
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
                else problem_user_prompt(state["skill"], state["language"], state["difficulty"])
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
) -> GeneratedProblem:
    # NOTE: this produces validated content only. Running the reference solution through
    # the sandbox and persisting problem_versions/tests is milestone 6's job.
    # A pasted problem is one-of-a-kind — never cached under the generic skill key, which
    # would otherwise poison the bank with someone else's specific question.
    key = (
        cache_key("problem", skill, language, difficulty)
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
