from app.execution.domain.models import ExecutionRequest
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.execution.infrastructure.composite_executor import CompositeExecutor
from app.shared.hashing import hash_output
from app.shared.types import Language


class _RecordingExecutor:
    def __init__(self, name: str) -> None:
        self.name = name
        self.received: list[ExecutionRequest] = []

    async def execute(self, request: ExecutionRequest):
        self.received.append(request)
        return
        yield  # pragma: no cover - makes this an async generator


async def test_routes_python_to_citron() -> None:
    citron, local = _RecordingExecutor("citron"), _RecordingExecutor("local")
    executor = CompositeExecutor(citron=citron, local=local)
    request = ExecutionRequest(
        language=Language.PYTHON,
        code="print(1)",
        test_cases=[ExecutionTestCase(id="t1", input="", output_hash=hash_output("x"))],
    )

    _ = [r async for r in executor.execute(request)]

    assert len(citron.received) == 1
    assert len(local.received) == 0


async def test_routes_javascript_to_local_fallback() -> None:
    citron, local = _RecordingExecutor("citron"), _RecordingExecutor("local")
    executor = CompositeExecutor(citron=citron, local=local)
    request = ExecutionRequest(
        language=Language.JAVASCRIPT,
        code="console.log(1)",
        test_cases=[ExecutionTestCase(id="t1", input="", output_hash=hash_output("x"))],
    )

    _ = [r async for r in executor.execute(request)]

    assert len(local.received) == 1
    assert len(citron.received) == 0
