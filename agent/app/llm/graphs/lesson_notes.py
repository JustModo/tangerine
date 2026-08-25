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
    problem_title: str | None
    statement_md: str | None
    tags: list[str] | None
    reference_solution: str | None
    result: GeneratedLessonNotes | None
    error: str | None
    attempts: int


def build_lesson_notes_graph(provider: LLMProvider):
    async def generate(state: LessonNotesGraphState) -> LessonNotesGraphState:
        request = StructuredGenerationRequest(
            system_prompt=LESSON_NOTES_SYSTEM_PROMPT,
            user_prompt=lesson_notes_user_prompt(
                state["skill"],
                state["language"],
                state["level"],
                problem_title=state["problem_title"],
                statement_md=state["statement_md"],
                tags=state["tags"],
                reference_solution=state["reference_solution"],
            ),
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
    problem_id: str | None = None,
    problem_title: str | None = None,
    statement_md: str | None = None,
    tags: list[str] | None = None,
    reference_solution: str | None = None,
) -> GeneratedLessonNotes:
    # One lesson per (problem, language, level) once a problem is known — a lesson written
    # against this problem's solution is not reusable for the next problem on the same
    # skill. Without a problem it falls back to the shared per-skill lesson. The version
    # segment is the cache's only invalidation lever.
    key = (
        cache_key(
            "lesson_notes", LESSON_NOTES_VERSION, problem_id or skill, language, level
        )
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
            "problem_title": problem_title,
            "statement_md": statement_md,
            "tags": tags,
            "reference_solution": reference_solution,
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
