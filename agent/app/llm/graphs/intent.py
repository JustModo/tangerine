from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.prompts.intent import INTENT_SYSTEM_PROMPT
from app.llm.schemas.intent import ClassifiedIntent


class IntentGraphState(TypedDict):
    message: str
    result: ClassifiedIntent | None


def build_intent_graph(provider: LLMProvider):
    async def classify(state: IntentGraphState) -> IntentGraphState:
        request = StructuredGenerationRequest(
            system_prompt=INTENT_SYSTEM_PROMPT, user_prompt=state["message"]
        )
        result = await provider.generate_structured(request, ClassifiedIntent)
        return {**state, "result": result}

    graph = StateGraph(IntentGraphState)
    graph.add_node("classify", classify)
    graph.set_entry_point("classify")
    graph.add_edge("classify", END)
    return graph.compile()


async def classify_intent(provider: LLMProvider, message: str) -> ClassifiedIntent:
    graph = build_intent_graph(provider)
    final_state = await graph.ainvoke({"message": message, "result": None})
    assert final_state["result"] is not None
    return final_state["result"]
