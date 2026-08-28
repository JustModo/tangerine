"""Server-sent-event framing, with the error case built in.

Every SSE endpoint here streams work that can fail after the response headers are already
out — Citron going away, Gemini rate-limiting, an API key revoked mid-session. Without a
terminal error frame the stream just stops, and the browser cannot tell that apart from a
normal finish: the client clears its "streaming" state and the user is left staring at
nothing. So the contract is that a stream ALWAYS ends with either `event: done` or a
`{"type": "error"}` frame, never with silence.
"""

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
    """Wraps an event iterator in SSE framing and guarantees a terminal frame.

    `context` only ever reaches the log — the client gets `error_message`, so an internal
    failure can't leak a stack trace or a provider's raw response into the browser."""
    try:
        async for event in events:
            yield encode(event)
    except Exception:
        logger.exception("SSE stream failed (%s)", context)
        yield sse_frame({"type": "error", "message": error_message})
        return
    yield "event: done\ndata: {}\n\n"
