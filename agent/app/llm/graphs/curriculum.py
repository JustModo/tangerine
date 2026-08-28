from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.graphs.shared import attempt, cached_generate, route, run_graph
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.prompts.curriculum import CURRICULUM_SYSTEM_PROMPT, curriculum_user_prompt
from app.llm.schemas.curriculum import GeneratedCurriculum


class CurriculumGraphState(TypedDict):
    topic: str
    language: str
    level: str
    step_count: int | None
    target_problem: str | None
    known_skills: list[str]
    result: GeneratedCurriculum | None
    error: str | None
    attempts: int


def build_curriculum_graph(provider: LLMProvider):
    async def generate(state: CurriculumGraphState) -> CurriculumGraphState:
        return await attempt(provider, state, CURRICULUM_SYSTEM_PROMPT, curriculum_user_prompt(
                state["topic"],
                state["language"],
                state["level"],
                state["step_count"],
                state["target_problem"],
                state["known_skills"],
            ), GeneratedCurriculum)

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
    step_count: int | None = None,
    target_problem: str | None = None,
    known_skills: list[str] | None = None,
) -> GeneratedCurriculum:
    # Same request always warrants the same curriculum — a safe, valuable cache candidate,
    # unlike per-submission coaching feedback. A pasted target problem makes it
    # one-of-a-kind, so it is never cached; step count and the mastered skills both shape
    # the plan, so both join the key.
    return await cached_generate(
        cache,
        None
        if target_problem
        else ["curriculum", topic, language, level, str(step_count), *sorted(known_skills or [])],
        GeneratedCurriculum,
        lambda: run_graph(
            build_curriculum_graph(provider),
            {
                "topic": topic,
                "language": language,
                "level": level,
                "step_count": step_count,
                "target_problem": target_problem,
                "known_skills": sorted(known_skills or []),
            },
            "Curriculum generation",
        ),
    )
