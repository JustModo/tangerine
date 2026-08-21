from pathlib import Path

import httpx

from app.execution.domain.models import ExecutionRequest, ExecutionStatus, TestResult
from app.shared.config import get_settings
from app.shared.hashing import hash_output

# Citron status ids that mean "the program never produced a comparable result" (see
# API_DOCS.md's Status Codes table) — everything else we decide ourselves via hash_output,
# since we deliberately never send Citron a real expected_output (see class docstring).
_INFRA_FAILURE_STATUS = {
    5: ExecutionStatus.TIMEOUT,  # Time Limit Exceeded
    6: ExecutionStatus.ERROR,  # Compilation Error
    7: ExecutionStatus.ERROR,  # SIGSEGV
    8: ExecutionStatus.ERROR,  # SIGXFSZ
    9: ExecutionStatus.ERROR,  # SIGFPE
    10: ExecutionStatus.ERROR,  # SIGABRT
    11: ExecutionStatus.ERROR,  # NZEC
    12: ExecutionStatus.ERROR,  # Other / MLE / OLE
    13: ExecutionStatus.ERROR,  # Internal Error
}


class CitronAdapter:
    """CodeExecutor implementation backed by Citron (see /API_DOCS.md) — a real isolated
    (nsjail) sandbox, replacing the bare child_process.spawn-based Node runner this app
    started with. Deliberately never sends Citron a real expected_output: Tangerine's own
    hash-based ground truth (app/shared/hashing.py) stays the single source of truth for
    correctness, matching the invariant the original Node runner already established —
    Citron is used purely as an isolated execution engine here, not as the judge.

    Live-verified against the real `justmodo/citron:latest` image (PASSED/FAILED via our
    own hash, real compile-error surfacing) — see CompositeExecutor for how it's wired
    into the live routers (Citron for c/cpp/java/python; LocalSubprocessExecutor is the
    JS fallback since Citron's languages.toml has no JS runtime registered)."""

    def __init__(
        self,
        citron_url: str | None = None,
        auth_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = citron_url or settings.citron_url
        self._auth_token = auth_token if auth_token is not None else settings.citron_auth_token
        self._transport = transport

    async def execute(self, request: ExecutionRequest):
        headers = {"X-Judge-Token": self._auth_token} if self._auth_token else {}
        body = {
            "language": request.language.value,
            "source_code": Path(request.code_path).read_text(),
            "testcases": [{"stdin": tc.input, "expected_output": ""} for tc in request.test_cases],
        }

        async with httpx.AsyncClient(timeout=60.0, transport=self._transport) as client:
            response = await client.post(f"{self._base_url}/submissions", json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        compile_info = data.get("compile") or {}
        if compile_info.get("success") is False:
            error_message = compile_info.get("output") or "compilation failed"
            for test_case in request.test_cases:
                yield TestResult(
                    id=test_case.id,
                    status=ExecutionStatus.ERROR,
                    input=test_case.input,
                    error=error_message,
                )
            return

        for test_case, tc_result in zip(request.test_cases, data.get("testcases", [])):
            status_id = (tc_result.get("status") or {}).get("id")
            stdout = tc_result.get("stdout") or ""

            if status_id in _INFRA_FAILURE_STATUS:
                status = _INFRA_FAILURE_STATUS[status_id]
            else:
                status = (
                    ExecutionStatus.PASSED
                    if hash_output(stdout) == test_case.output_hash
                    else ExecutionStatus.FAILED
                )

            wall_time_ms = tc_result.get("wall_time_ms")
            yield TestResult(
                id=test_case.id,
                status=status,
                input=test_case.input,
                actual_output=stdout,
                error=tc_result.get("stderr") or None,
                execution_time_ms=str(wall_time_ms) if wall_time_ms is not None else None,
            )
