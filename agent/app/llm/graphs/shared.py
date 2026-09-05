"""What all four generation graphs do identically.

Each graph is one node that asks for structured output and retries on a schema rejection,
wrapped in a semantic cache. Only the prompt differs, so the attempt bookkeeping and the
cache dance live here rather than four times over.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import StructuredGenerationRequest
from app.llm.infrastructure.cache import SqliteLLMCache, cache_key
from app.llm.infrastructure.gemini.mapping import SchemaValidationError

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 3


def rejection_note(error: str | None) -> str:
    """Appended to the user prompt on a retry.

    Without it a retry re-sends a byte-identical prompt and depends entirely on sampling to
    come out different — three chances at the same dice. Naming the failure is the same
    trick patch_problem already uses to repair a rejected problem."""
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
    """One generation, folded back into graph state. A schema rejection is recorded rather
    than raised so the graph can route to a retry that knows what went wrong."""
    request = StructuredGenerationRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt + rejection_note(state.get("error")),
    )
    try:
        result = await provider.generate_structured(request, response_model)
        return {**state, "result": result, "error": None}
    except SchemaValidationError as exc:
        return {**state, "error": str(exc), "attempts": state["attempts"] + 1}


def route(state: dict) -> str:
    if state["result"] is not None or state["attempts"] >= MAX_ATTEMPTS:
        return "done"
    return "retry"


async def run_graph(graph, state: dict, what: str):
    """Invokes a compiled graph and insists on a result. Every graph seeds the same three
    bookkeeping fields, so callers pass only their own inputs."""
    final = await graph.ainvoke({**state, "result": None, "error": None, "attempts": 0})
    if final["result"] is None:
        raise SchemaValidationError(
            f"{what} failed after {MAX_ATTEMPTS} attempts: {final['error']}"
        )
    return final["result"]


async def cached_generate[T: BaseModel](
    cache: SqliteLLMCache | None,
    key_parts: list[str] | None,
    response_model: type[T],
    run: Callable[[], Awaitable[T]],
    refresh: bool = False,
) -> T:
    """Wraps a graph run in the semantic cache. `key_parts` of None means this result is
    one-of-a-kind and must never be cached — a pasted problem, say.

    refresh skips the READ, not the write: a regenerate replaces the cached entry rather
    than bypassing it forever."""
    key = cache_key(*key_parts) if cache is not None and key_parts is not None else None
    if key is not None and not refresh:
        cached = await cache.get(key)
        if cached is not None:
            return response_model.model_validate_json(cached)

    result = await run()
    if key is not None:
        await cache.set(key, result.model_dump_json())
    return result
