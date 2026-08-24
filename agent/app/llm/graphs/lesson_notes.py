from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.infrastructure.cache import SqliteLLMCache, cache_key
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.prompts.lesson_notes import (
    LESSON_NOTES_SYSTEM_PROMPT,
    LESSON_NOTES_VERSION,
    lesson_notes_user_prompt,
)
from app.llm.schemas.lesson_notes import GeneratedLessonNotes

MAX_ATTEMPTS = 3


class LessonNotesGraphState(TypedDict):
    skill: str
    language: str
    level: str
    result: GeneratedLessonNotes | None
    error: str | None
    attempts: int


def build_lesson_notes_graph(provider: LLMProvider):
    async def generate(state: LessonNotesGraphState) -> LessonNotesGraphState:
        request = StructuredGenerationRequest(
            system_prompt=LESSON_NOTES_SYSTEM_PROMPT,
            user_prompt=lesson_notes_user_prompt(state["skill"], state["language"], state["level"]),
        )
        try:
            result = await provider.generate_structured(request, GeneratedLessonNotes)
            return {**state, "result": result, "error": None}
        except SchemaValidationError as exc:
            return {**state, "error": str(exc), "attempts": state["attempts"] + 1}

    def route(state: LessonNotesGraphState) -> str:
        if state["result"] is not None or state["attempts"] >= MAX_ATTEMPTS:
            return "done"
        return "retry"

    graph = StateGraph(LessonNotesGraphState)
    graph.add_node("generate", generate)
    graph.set_entry_point("generate")
    graph.add_conditional_edges("generate", route, {"retry": "generate", "done": END})
    return graph.compile()


async def generate_lesson_notes(
    provider: LLMProvider,
    skill: str,
    language: str,
    level: str,
    cache: SqliteLLMCache | None = None,
    refresh: bool = False,
) -> GeneratedLessonNotes:
    # The same (skill, language, level) always warrants the same lesson, so this is cached
    # once and shared across every plan, session, and user — the whole reason lessons stay
    # token-cheap. The version segment is the only invalidation lever the cache has.
    key = (
        cache_key("lesson_notes", LESSON_NOTES_VERSION, skill, language, level)
        if cache is not None
        else None
    )
    # refresh skips the READ, not the write: a regenerate replaces the cached entry rather
    # than bypassing it forever.
    if cache is not None and key is not None and not refresh:
        cached = await cache.get(key)
        if cached is not None:
            return GeneratedLessonNotes.model_validate_json(cached)

    graph = build_lesson_notes_graph(provider)
    final_state = await graph.ainvoke(
        {
            "skill": skill,
            "language": language,
            "level": level,
            "result": None,
            "error": None,
            "attempts": 0,
        }
    )
    if final_state["result"] is None:
        raise SchemaValidationError(
            f"Lesson notes generation failed after {MAX_ATTEMPTS} attempts: {final_state['error']}"
        )

    if cache is not None and key is not None:
        await cache.set(key, final_state["result"].model_dump_json())

    return final_state["result"]
