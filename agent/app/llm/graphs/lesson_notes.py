import logging
from collections.abc import Awaitable, Callable
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.graphs.shared import MAX_SCHEMA_ATTEMPTS, attempt, cached_generate, route, run_graph
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.prompts.lesson_notes import (
    LESSON_NOTES_SYSTEM_PROMPT,
    LESSON_NOTES_VERSION,
    lesson_notes_user_prompt,
)
from app.llm.schemas.lesson_notes import GeneratedLessonNotes

logger = logging.getLogger(__name__)

# Given a lesson and its language, what is wrong with it, or None. Injected rather than
# imported so the graph never has to know that checking it means running a sandbox.
LessonNotesVerifier = Callable[[GeneratedLessonNotes, str], Awaitable[str | None]]


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


def build_lesson_notes_graph(provider: LLMProvider, verifier: LessonNotesVerifier | None = None):
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

    async def verify(state: LessonNotesGraphState) -> LessonNotesGraphState:
        """Rejects a lesson whose own output blocks are wrong, exactly like a schema
        rejection: clearing the result routes back through generate with the reason.

        A lesson that is merely unverified still beats no lesson, so the last attempt is
        served either way, and a sandbox that cannot be reached is never fatal."""
        result = state["result"]
        if verifier is None or result is None:
            return state
        try:
            error = await verifier(result, state["language"])
        except Exception:
            logger.warning("Lesson code verification could not run", exc_info=True)
            return state
        if error is None:
            return state

        attempts = state["attempts"] + 1
        if attempts >= MAX_SCHEMA_ATTEMPTS:
            logger.warning("Serving lesson notes with an unverified trace: %s", error)
            return {**state, "attempts": attempts}
        return {**state, "result": None, "error": error, "attempts": attempts}

    graph = StateGraph(LessonNotesGraphState)
    graph.add_node("generate", generate)
    graph.add_node("verify", verify)
    graph.set_entry_point("generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges("verify", route, {"retry": "generate", "done": END})
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
    verifier: LessonNotesVerifier | None = None,
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
            build_lesson_notes_graph(provider, verifier),
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
