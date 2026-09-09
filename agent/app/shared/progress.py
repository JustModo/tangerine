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
    queue: asyncio.Queue = asyncio.Queue()

    async def run() -> T:
        try:
            return await work(queue.put_nowait)
        finally:
            queue.put_nowait(_DONE)

    task = asyncio.create_task(run())
    while (stage := await queue.get()) is not _DONE:
        yield {"type": "stage", "stage": stage}

    yield encode_result(await task)
