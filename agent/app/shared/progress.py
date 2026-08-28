"""Turning a slow call that reports its own progress into a stream of events.

Some calls are instant on a good day and half a minute on a bad one — preparing a problem
is a bank lookup or a generate/validate/repair chain, and only the call itself knows which.
Those calls report progress through a plain `on_stage(name)` callback so that nothing below
the API layer has to know SSE exists; this module is the one place that adapts such a
callback into an async iterator a stream can consume.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

StageReporter = Callable[[str], None]

_DONE = object()


async def stage_stream[T](
    work: Callable[[StageReporter], Awaitable[T]],
    encode_result: Callable[[T], dict],
) -> AsyncIterator[dict]:
    """Runs `work`, yielding `{"type": "stage", "stage": ...}` for each stage it reports,
    then one final frame from `encode_result`.

    Whatever `work` raises propagates out of the iterator, so the caller decides which
    failures deserve a message of their own and which fall through to a generic one.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def run() -> T:
        try:
            return await work(queue.put_nowait)
        finally:
            # In a finally, so a failure still releases the drain loop below instead of
            # leaving the request hanging on a queue nobody will ever feed again.
            queue.put_nowait(_DONE)

    task = asyncio.create_task(run())
    while (stage := await queue.get()) is not _DONE:
        yield {"type": "stage", "stage": stage}

    yield encode_result(await task)
