from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.graphs.shared import attempt, route, run_graph
from app.llm.prompts.plan_edit import PLAN_EDIT_SYSTEM_PROMPT, plan_edit_user_prompt
from app.llm.schemas.plan_edit import RevisedCurriculum


class PlanEditGraphState(TypedDict):
    topic: str
    language: str
    level: str
    current_steps: str
    instruction: str
    result: RevisedCurriculum | None
    error: str | None
    attempts: int


def build_plan_edit_graph(provider: LLMProvider):
    async def generate(state: PlanEditGraphState) -> PlanEditGraphState:
        return await attempt(provider, state, PLAN_EDIT_SYSTEM_PROMPT, plan_edit_user_prompt(
                state["topic"],
                state["language"],
                state["level"],
                state["current_steps"],
                state["instruction"],
            ), RevisedCurriculum)

    graph = StateGraph(PlanEditGraphState)
    graph.add_node("generate", generate)
    graph.set_entry_point("generate")
    graph.add_conditional_edges("generate", route, {"retry": "generate", "done": END})
    return graph.compile()


async def revise_curriculum(
    provider: LLMProvider,
    topic: str,
    language: str,
    level: str,
    current_steps: str,
    instruction: str,
) -> RevisedCurriculum:
    # Uncached: the output depends on the learner's current plan and a free-text
    # instruction, so it is never the same twice — the opposite of what SqliteLLMCache is for.
    return await run_graph(
        build_plan_edit_graph(provider),
        {
            "topic": topic,
            "language": language,
            "level": level,
            "current_steps": current_steps,
            "instruction": instruction,
        },
        "Plan revision",
    )
