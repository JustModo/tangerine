"""Retrying the Gemini calls that failed for reasons that have nothing to do with us.

Distinct from the schema retry in the graphs: that one re-asks because the model answered
badly, this one re-asks because the call never really happened. A rate limit or an
overloaded backend is not a bad answer, and retrying it immediately — the way a schema
retry does — makes a rate limit worse rather than better.
"""

import asyncio
import logging
import random

import httpx
from google.genai import errors

logger = logging.getLogger(__name__)

MAX_TRANSPORT_ATTEMPTS = 3
BASE_DELAY_SECONDS = 1.0

# 429 rate limit, 500/502/503/504 backend trouble. Every other code — a bad key, a malformed
# request, a safety block — means the same call will fail the same way forever.
RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})


def is_retryable(exc: BaseException) -> bool:
    # httpx.TransportError covers DNS failures, dropped connections, timeouts — the network
    # never even reached Gemini, so it's the same "try again" case as a 5xx from Gemini itself.
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, errors.APIError) and exc.code in RETRYABLE_CODES


async def backoff_delay(attempt: int, exc: BaseException, what: str) -> None:
    """Waits out one failed attempt. Jittered, because a plan generating several problems
    back to back would otherwise line its retries up on the same schedule and hit the same
    limit together."""
    delay = BASE_DELAY_SECONDS * 2**attempt + random.uniform(0, 0.5)
    logger.warning(
        "%s failed with %s, retrying in %.1fs (attempt %d/%d)",
        what,
        getattr(exc, "code", None) or type(exc).__name__,
        delay,
        attempt + 1,
        MAX_TRANSPORT_ATTEMPTS,
    )
    await asyncio.sleep(delay)


async def with_retry(call, what: str):
    """Runs `call()`, retrying transient API failures with exponential backoff."""
    for attempt in range(MAX_TRANSPORT_ATTEMPTS):
        try:
            return await call()
        except Exception as exc:
            if not is_retryable(exc) or attempt == MAX_TRANSPORT_ATTEMPTS - 1:
                raise
            await backoff_delay(attempt, exc, what)
