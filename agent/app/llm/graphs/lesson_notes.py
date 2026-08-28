from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.graphs.shared import attempt, cached_generate, route, run_graph
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.prompts.lesson_notes import (
    LESSON_NOTES_SYSTEM_PROMPT,
    LESSON_NOTES_VERSION,
    lesson_notes_user_prompt,
)
from app.llm.schemas.lesson_notes import GeneratedLessonNotes


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
        return await attempt(provider, state, LESSON_NOTES_SYSTEM_PROMPT, lesson_notes_user_prompt(
                state["skill"],
                state["language"],
                state["level"],
                problem_title=state["problem_title"],
                statement_md=state["statement_md"],
                tags=state["tags"],
                reference_solution=state["reference_solution"],
            ), GeneratedLessonNotes)

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
    return await cached_generate(
        cache,
        ["lesson_notes", LESSON_NOTES_VERSION, problem_id or skill, language, level],
        GeneratedLessonNotes,
        lambda: run_graph(
            build_lesson_notes_graph(provider),
            {
                "skill": skill,
                "language": language,
                "level": level,
                "problem_title": problem_title,
                "statement_md": statement_md,
                "tags": tags,
                "reference_solution": reference_solution,
            },
            "Lesson notes generation",
        ),
        refresh=refresh,
    )
