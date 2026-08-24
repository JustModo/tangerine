from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.prompts.plan_edit import PLAN_EDIT_SYSTEM_PROMPT, plan_edit_user_prompt
from app.llm.schemas.plan_edit import RevisedCurriculum

MAX_ATTEMPTS = 3


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
        request = StructuredGenerationRequest(
            system_prompt=PLAN_EDIT_SYSTEM_PROMPT,
            user_prompt=plan_edit_user_prompt(
                state["topic"],
                state["language"],
                state["level"],
                state["current_steps"],
                state["instruction"],
            ),
        )
        try:
            result = await provider.generate_structured(request, RevisedCurriculum)
            return {**state, "result": result, "error": None}
        except SchemaValidationError as exc:
            return {**state, "error": str(exc), "attempts": state["attempts"] + 1}

    def route(state: PlanEditGraphState) -> str:
        if state["result"] is not None or state["attempts"] >= MAX_ATTEMPTS:
            return "done"
        return "retry"

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
    graph = build_plan_edit_graph(provider)
    final_state = await graph.ainvoke(
        {
            "topic": topic,
            "language": language,
            "level": level,
            "current_steps": current_steps,
            "instruction": instruction,
            "result": None,
            "error": None,
            "attempts": 0,
        }
    )
    if final_state["result"] is None:
        raise SchemaValidationError(
            f"Plan revision failed after {MAX_ATTEMPTS} attempts: {final_state['error']}"
        )
    return final_state["result"]
