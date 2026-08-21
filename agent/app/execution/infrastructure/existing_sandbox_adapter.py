import json
from collections.abc import AsyncIterator

import httpx

from app.execution.domain.models import ExecutionRequest, ExecutionStatus, TestResult
from app.shared.config import get_settings


class ExistingSandboxAdapter:
    """CodeExecutor implementation that wraps the existing Node sandbox's POST /api/run SSE
    endpoint (web/server/routes/api.ts) rather than re-implementing code execution (plan.md §13-15).
    Re-streams each normalized result as it arrives instead of buffering, to preserve run.tsx's
    existing real-time feedback UX."""

    def __init__(
        self,
        node_sandbox_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = node_sandbox_url or get_settings().node_sandbox_url
        self._transport = transport

    async def execute(self, request: ExecutionRequest) -> AsyncIterator[TestResult]:
        body = {
            "language": request.language.value,
            "codePath": request.code_path,
            "testCases": [
                {"id": tc.id, "input": tc.input, "output": tc.output_hash}
                for tc in request.test_cases
            ],
        }
        async with httpx.AsyncClient(timeout=None, transport=self._transport) as client:
            async with client.stream("POST", f"{self._base_url}/api/run", json=body) as response:
                response.raise_for_status()
                event_type = "message"
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line.removeprefix("event:").strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    payload = line.removeprefix("data:").strip()
                    if event_type == "done":
                        break
                    if event_type == "error":
                        data = json.loads(payload)
                        raise RuntimeError(data.get("message", "sandbox execution error"))
                    data = json.loads(payload)
                    yield TestResult(
                        id=data["id"],
                        status=ExecutionStatus(data["status"]),
                        input=data["input"],
                        actual_output=data.get("actualOutput"),
                        error=data.get("error"),
                        execution_time_ms=data.get("executionTime"),
                    )
