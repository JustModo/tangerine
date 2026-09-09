import json
import logging
from collections.abc import AsyncIterator, Callable

logger = logging.getLogger(__name__)

GENERIC_ERROR = "Something went wrong on the server. Try again in a moment."


def sse_frame(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def sse_stream(
    events: AsyncIterator,
    *,
    context: str,
    encode: Callable[[object], str] = sse_frame,
    error_message: str = GENERIC_ERROR,
) -> AsyncIterator[str]:
    try:
        async for event in events:
            yield encode(event)
    except Exception:
        logger.exception("SSE stream failed (%s)", context)
        yield sse_frame({"type": "error", "message": error_message})
        return
    yield "event: done\ndata: {}\n\n"
