from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.infrastructure.cache import SqliteLLMCache, cache_key
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.prompts.curriculum import CURRICULUM_SYSTEM_PROMPT, curriculum_user_prompt
from app.llm.schemas.curriculum import GeneratedCurriculum

MAX_ATTEMPTS = 3


class CurriculumGraphState(TypedDict):
    topic: str
    language: str
    level: str
    result: GeneratedCurriculum | None
    error: str | None
    attempts: int


def build_curriculum_graph(provider: LLMProvider):
    async def generate(state: CurriculumGraphState) -> CurriculumGraphState:
        request = StructuredGenerationRequest(
            system_prompt=CURRICULUM_SYSTEM_PROMPT,
            user_prompt=curriculum_user_prompt(state["topic"], state["language"], state["level"]),
        )
        try:
            result = await provider.generate_structured(request, GeneratedCurriculum)
            return {**state, "result": result, "error": None}
        except SchemaValidationError as exc:
            return {**state, "error": str(exc), "attempts": state["attempts"] + 1}

    def route(state: CurriculumGraphState) -> str:
        if state["result"] is not None or state["attempts"] >= MAX_ATTEMPTS:
            return "done"
        return "retry"

    graph = StateGraph(CurriculumGraphState)
    graph.add_node("generate", generate)
    graph.set_entry_point("generate")
    graph.add_conditional_edges("generate", route, {"retry": "generate", "done": END})
    return graph.compile()


async def generate_curriculum(
    provider: LLMProvider,
    topic: str,
    language: str,
    level: str,
    cache: SqliteLLMCache | None = None,
) -> GeneratedCurriculum:
    # Same (topic, language, level) always warrants the same curriculum — a safe, valuable
    # cache candidate, unlike per-submission coaching feedback (plan.md §38).
    key = cache_key("curriculum", topic, language, level) if cache is not None else None
    if cache is not None and key is not None:
        cached = await cache.get(key)
        if cached is not None:
            return GeneratedCurriculum.model_validate_json(cached)

    graph = build_curriculum_graph(provider)
    final_state = await graph.ainvoke(
        {
            "topic": topic,
            "language": language,
            "level": level,
            "result": None,
            "error": None,
            "attempts": 0,
        }
    )
    if final_state["result"] is None:
        raise SchemaValidationError(
            f"Curriculum generation failed after {MAX_ATTEMPTS} attempts: {final_state['error']}"
        )

    if cache is not None and key is not None:
        await cache.set(key, final_state["result"].model_dump_json())

    return final_state["result"]
