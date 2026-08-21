from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.prompts.coaching import COACHING_SYSTEM_PROMPT, coaching_user_prompt
from app.llm.schemas.coaching import CoachingFeedback


class CoachingGraphState(TypedDict):
    evaluation_summary: dict
    result: CoachingFeedback | None


def build_coaching_graph(provider: LLMProvider):
    async def generate(state: CoachingGraphState) -> CoachingGraphState:
        request = StructuredGenerationRequest(
            system_prompt=COACHING_SYSTEM_PROMPT,
            user_prompt=coaching_user_prompt(state["evaluation_summary"]),
        )
        result = await provider.generate_structured(request, CoachingFeedback)
        return {**state, "result": result}

    graph = StateGraph(CoachingGraphState)
    graph.add_node("generate", generate)
    graph.set_entry_point("generate")
    graph.add_edge("generate", END)
    return graph.compile()


async def generate_coaching_feedback(
    provider: LLMProvider, evaluation_summary: dict
) -> CoachingFeedback:
    # Not called anywhere yet — evaluation (milestone 7) is what will invoke this.
    graph = build_coaching_graph(provider)
    final_state = await graph.ainvoke({"evaluation_summary": evaluation_summary, "result": None})
    assert final_state["result"] is not None
    return final_state["result"]
