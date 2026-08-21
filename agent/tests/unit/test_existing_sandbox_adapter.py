import httpx

from app.execution.domain.models import ExecutionRequest, ExecutionStatus, TestCase
from app.execution.infrastructure.existing_sandbox_adapter import ExistingSandboxAdapter
from app.shared.types import Language


def _fake_sse_transport(body: bytes) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/run"
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


async def test_execute_streams_normalized_results() -> None:
    sse_body = (
        b'data: {"id": "t1", "status": "PASSED", "input": "1", "actualOutput": "1", "executionTime": "5"}\n\n'
        b'data: {"id": "t2", "status": "FAILED", "input": "2", "actualOutput": "3", "executionTime": "4"}\n\n'
        b"event: done\ndata: {}\n\n"
    )
    adapter = ExistingSandboxAdapter(
        node_sandbox_url="http://node.test", transport=_fake_sse_transport(sse_body)
    )
    request = ExecutionRequest(
        language=Language.PYTHON,
        code_path="/tmp/solution.py",
        test_cases=[TestCase(id="t1", input="1", output_hash="hash1")],
    )

    results = [result async for result in adapter.execute(request)]

    assert [r.id for r in results] == ["t1", "t2"]
    assert results[0].status == ExecutionStatus.PASSED
    assert results[1].status == ExecutionStatus.FAILED
    assert results[1].actual_output == "3"


async def test_execute_raises_on_sandbox_error_event() -> None:
    sse_body = b'event: error\ndata: {"message": "boom"}\n\n'
    adapter = ExistingSandboxAdapter(
        node_sandbox_url="http://node.test", transport=_fake_sse_transport(sse_body)
    )
    request = ExecutionRequest(language=Language.PYTHON, code_path="/tmp/x.py", test_cases=[])

    try:
        _ = [result async for result in adapter.execute(request)]
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "boom" in str(exc)
