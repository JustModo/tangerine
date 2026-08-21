import httpx

from app.execution.domain.models import ExecutionRequest, ExecutionStatus, TestResult
from app.shared.config import get_settings
from app.shared.hashing import hash_output

# Citron status ids that mean "the program never produced a comparable result" — these
# are the WIRE ids the deployed `justmodo/citron:latest` image actually returns, live-
# verified against a running container (id 4 = Wrong Answer, 5 = Time Limit Exceeded,
# 6 = Compilation Error, 7 = SIGSEGV, 11 = NZEC — confirmed directly, 2026-08-21). This
# does NOT match the sibling citron/ source tree's Go status.go const block, which uses
# different (0-indexed) numbering — that tree is evidently ahead of / different from
# what's actually baked into the pinned image, so the LIVE wire values win, not a static
# source read. Id 4 (Wrong Answer) and id 0-3 below it are intentionally absent — Wrong
# Answer still falls through to our own hash_output comparison, matching the class's
# whole design intent of ignoring Citron's own verdict.
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


def _error_detail(
    status: ExecutionStatus, stderr: str | None, message: str | None, status_description: str | None
) -> str | None:
    # Only fabricate an error string for statuses that ARE errors — never invent one for
    # a plain PASSED/FAILED comparison. `message` is Citron's own "why did this
    # citron-level failure happen" field (distinct from stderr, which is the user
    # program's own output) — it's the only signal available when a killed/OOM'd/timed-out
    # process never got the chance to write anything to stderr itself.
    if status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT):
        return stderr or message or status_description
    return stderr or None


class CitronAdapter:
    """CodeExecutor implementation backed by Citron — a real isolated
    (nsjail) sandbox, replacing the bare child_process.spawn-based Node runner this app
    started with. Deliberately never sends Citron a real expected_output: Tangerine's own
    hash-based ground truth (app/shared/hashing.py) stays the single source of truth for
    correctness, matching the invariant the original Node runner already established —
    Citron is used purely as an isolated execution engine here, not as the judge.

    Live-verified against the real `justmodo/citron:latest` image (PASSED/FAILED via our
    own hash, real compile-error surfacing). The sole CodeExecutor in this app — Citron's
    languages.toml covers exactly the four languages this app supports (c/cpp/java/python),
    so no fallback/routing layer is needed."""

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
            "source_code": request.code,
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

        # zip() alone would silently truncate to the shorter sequence, so a short reply
        # from Citron would make test cases vanish with no explanation. Pad instead, and
        # surface each missing one as an explicit ERROR.
        returned = data.get("testcases") or []
        padded = list(returned) + [None] * max(0, len(request.test_cases) - len(returned))
        for test_case, tc_result in zip(request.test_cases, padded):
            if tc_result is None:
                yield TestResult(
                    id=test_case.id,
                    status=ExecutionStatus.ERROR,
                    input=test_case.input,
                    error="The sandbox returned no result for this test case.",
                )
                continue
            tc_status = tc_result.get("status") or {}
            status_id = tc_status.get("id")
            status_description = tc_status.get("description")
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
                error=_error_detail(status, tc_result.get("stderr"), tc_result.get("message"), status_description),
                execution_time_ms=str(wall_time_ms) if wall_time_ms is not None else None,
                exit_code=tc_result.get("exit_code"),
                signal=tc_result.get("signal"),
                memory_kb=tc_result.get("memory_kb"),
                status_description=status_description,
                stdout_truncated=bool(tc_result.get("stdout_truncated")),
                stderr_truncated=bool(tc_result.get("stderr_truncated")),
            )
