import logging
from collections.abc import Callable
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.graphs.shared import MAX_SCHEMA_ATTEMPTS, attempt, run_graph
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.prompts.problem import (
    adapt_problem_user_prompt,
    adapt_system_prompt,
    critique_system_prompt,
    critique_user_prompt,
    patch_problem_user_prompt,
    patch_system_prompt,
    problem_system_prompt,
    problem_user_prompt,
    revise_problem_user_prompt,
    revise_system_prompt,
)
from app.llm.schemas.problem import (
    GeneratedProblem,
    ProblemCritique,
    ProblemPatch,
    ProblemRevision,
)

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 1


class ProblemGraphState(TypedDict):
    skill: str
    language: str
    difficulty: str
    source_problem: str | None
    avoid_titles: list[str]
    result: GeneratedProblem | None
    error: str | None
    attempts: int
    violations: list[str]
    revisions: int


def _route_problem(state: ProblemGraphState) -> str:
    if state["result"] is None:
        return "done" if state["attempts"] >= MAX_SCHEMA_ATTEMPTS else "generate"
    if state["violations"] and state["revisions"] < MAX_REVISION_ROUNDS:
        return "revise"
    return "done"


def build_problem_graph(provider: LLMProvider, on_stage: Callable[[str], None] | None = None):
    stage = on_stage or (lambda _: None)

    async def generate(state: ProblemGraphState) -> ProblemGraphState:
        source = state["source_problem"]
        system_prompt = (
            adapt_system_prompt(state["language"])
            if source
            else problem_system_prompt(state["language"])
        )
        user_prompt = (
            adapt_problem_user_prompt(source, state["language"])
            if source
            else problem_user_prompt(
                state["skill"],
                state["language"],
                state["difficulty"],
                state["avoid_titles"],
            )
        )
        return await attempt(provider, state, system_prompt, user_prompt, GeneratedProblem)

    async def critique(state: ProblemGraphState) -> ProblemGraphState:
        result = state["result"]
        if result is None or state["revisions"] >= MAX_REVISION_ROUNDS:
            return state
        stage("evaluating")
        request = StructuredGenerationRequest(
            system_prompt=critique_system_prompt(state["language"]),
            user_prompt=critique_user_prompt(result, state["source_problem"]),
        )
        try:
            verdict = await provider.generate_structured(request, ProblemCritique)
        except Exception:
            logger.warning("Problem critique could not run", exc_info=True)
            return {**state, "violations": []}
        if verdict.approved or not verdict.violations:
            return {**state, "violations": []}
        logger.info(
            "Problem %r rejected by critique: %s", result.title, "; ".join(verdict.violations)
        )
        return {**state, "violations": verdict.violations}

    async def revise(state: ProblemGraphState) -> ProblemGraphState:
        result = state["result"]
        stage("revising")
        request = StructuredGenerationRequest(
            system_prompt=revise_system_prompt(state["language"]),
            user_prompt=revise_problem_user_prompt(
                result, state["violations"], state["source_problem"]
            ),
        )
        try:
            revision = await provider.generate_structured(request, ProblemRevision)
        except Exception:
            logger.warning("Problem revision could not run", exc_info=True)
            return {**state, "violations": [], "revisions": MAX_REVISION_ROUNDS}
        update = {
            name: value
            for name in revision.model_fields_set
            if (value := getattr(revision, name)) is not None
        }
        if state["source_problem"]:
            update.pop("statement_md", None)
        return {
            **state,
            "result": result.model_copy(update=update) if update else result,
            "violations": [],
            "revisions": state["revisions"] + 1,
        }

    graph = StateGraph(ProblemGraphState)
    graph.add_node("generate", generate)
    graph.add_node("critique", critique)
    graph.add_node("revise", revise)
    graph.set_entry_point("generate")
    graph.add_edge("generate", "critique")
    graph.add_edge("revise", "critique")
    graph.add_conditional_edges(
        "critique", _route_problem, {"generate": "generate", "revise": "revise", "done": END}
    )
    return graph.compile()


async def generate_problem(
    provider: LLMProvider,
    skill: str,
    language: str,
    difficulty: str,
    source_problem: str | None = None,
    avoid_titles: list[str] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> GeneratedProblem:
    """Deliberately uncached. A cache key of (skill, language, difficulty, avoid titles) is
    identical for the first step of every new plan on a skill, so caching handed every
    learner the byte-identical question — the repetition this is meant to avoid. Lesson
    notes and curricula are still cached; they are reference material, not the exercise."""
    return await run_graph(
        build_problem_graph(provider, on_stage),
        {
            "skill": skill,
            "language": language,
            "difficulty": difficulty,
            "source_problem": source_problem,
            "avoid_titles": avoid_titles or [],
            "violations": [],
            "revisions": 0,
        },
        "Problem generation",
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
