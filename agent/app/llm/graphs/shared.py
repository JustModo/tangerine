"""Shared graph compilation, retries, and caching utilities for LLM generation."""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.infrastructure.cache import SqliteLLMCache, cache_key
from app.llm.infrastructure.gemini.mapping import SchemaValidationError

T = TypeVar("T", bound=BaseModel)

MAX_SCHEMA_ATTEMPTS = 3


def rejection_note(error: str | None) -> str:
    """Format schema error rejection note for retry prompt."""
    if not error:
        return ""
    return (
        "\n\nYour previous response was REJECTED:\n"
        f"{error}\n"
        "Fix exactly that and return valid JSON matching the schema. Do not repeat the "
        "mistake."
    )


async def attempt[T: BaseModel](
    provider: LLMProvider,
    state: dict,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
) -> dict:
    """Execute a structured generation attempt and update graph state."""
    request = StructuredGenerationRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt + rejection_note(state["error"]),
    )
    try:
        result = await provider.generate_structured(request, response_model)
        return {**state, "result": result, "error": None}
    except SchemaValidationError as exc:
        return {**state, "error": str(exc), "attempts": state["attempts"] + 1}


def compile_retry_graph(state_type, generate):
    """Compile single-node graph with conditional retry on schema validation failure."""
    graph = StateGraph(state_type)
    graph.add_node("generate", generate)
    graph.set_entry_point("generate")
    graph.add_conditional_edges("generate", route, {"retry": "generate", "done": END})
    return graph.compile()


def route(state: dict) -> str:
    if state["result"] is not None or state["attempts"] >= MAX_SCHEMA_ATTEMPTS:
        return "done"
    return "retry"


async def run_graph(graph, state: dict, what: str):
    """Invoke compiled generation graph with initial state and validation assertion."""
    final = await graph.ainvoke({**state, "result": None, "error": None, "attempts": 0})
    if final["result"] is None:
        raise SchemaValidationError(
            f"{what} failed after {MAX_SCHEMA_ATTEMPTS} attempts: {final['error']}"
        )
    return final["result"]


async def cached_generate[T: BaseModel](
    cache: SqliteLLMCache | None,
    key_parts: list[str] | None,
    response_model: type[T],
    run: Callable[[], Awaitable[T]],
    refresh: bool = False,
) -> T:
    """Execute cached structured generation."""
    key = cache_key(*key_parts) if cache is not None and key_parts is not None else None
    if key is not None and not refresh:
        cached = await cache.get(key)
        if cached is not None:
            return response_model.model_validate_json(cached)

    result = await run()
    if key is not None:
        await cache.set(key, result.model_dump_json())
    return result
