import httpx

from app.execution.domain.models import ExecutionRequest, ExecutionStatus
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.execution.infrastructure.citron_adapter import CitronAdapter
from app.shared.hashing import hash_output
from app.shared.types import Language


def _fake_citron_transport(body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/submissions"
        return httpx.Response(201, json=body)

    return httpx.MockTransport(handler)


async def test_execute_derives_pass_fail_from_our_own_hash_not_citrons_verdict() -> None:
    # Citron's own status says "Wrong Answer" (id 4, live-verified) for testcase 0 even
    # though the stdout actually matches our stored hash — the adapter must ignore
    # Citron's verdict and decide PASSED/FAILED itself via hash_output, per the class's
    # whole design intent (we never send Citron a real expected_output).
    citron_response = {
        "id": "abc123",
        "status": {"id": 4, "description": "Wrong Answer"},
        "compile": {"skipped": True, "success": True, "output": "", "duration_ms": 0, "cached": False},
        "wall_time_ms": 45,
        "testcases": [
            {
                "index": 0,
                "status": {"id": 4, "description": "Wrong Answer"},
                "stdout": "6",
                "exit_code": 0,
                "cpu_time_ms": 15,
                "wall_time_ms": 18,
                "memory_kb": 8192,
            },
            {
                "index": 1,
                "status": {"id": 4, "description": "Wrong Answer"},
                "stdout": "wrong",
                "exit_code": 0,
                "cpu_time_ms": 15,
                "wall_time_ms": 18,
                "memory_kb": 8192,
            },
        ],
    }

    adapter = CitronAdapter(
        citron_url="http://citron.test", transport=_fake_citron_transport(citron_response)
    )
    request = ExecutionRequest(
        language=Language.PYTHON,
        code="print(sum(int(x) for x in input().split()))",
        test_cases=[
            ExecutionTestCase(id="t0", input="1 2 3", output_hash=hash_output("6")),
            ExecutionTestCase(id="t1", input="1 2 3", output_hash=hash_output("6")),
        ],
    )

    results = [result async for result in adapter.execute(request)]

    assert results[0].status == ExecutionStatus.PASSED  # stdout "6" matches our hash
    assert results[1].status == ExecutionStatus.FAILED  # stdout "wrong" does not


async def test_execute_maps_infra_failure_statuses() -> None:
    # Live-verified wire id 5 = Time Limit Exceeded against the real justmodo/citron:latest
    # image (see the module-level comment on _INFRA_FAILURE_STATUS for how this was confirmed).
    citron_response = {
        "id": "abc123",
        "status": {"id": 5, "description": "Time Limit Exceeded"},
        "compile": {"skipped": True, "success": True, "output": "", "duration_ms": 0, "cached": False},
        "wall_time_ms": 4000,
        "testcases": [
            {
                "index": 0,
                "status": {"id": 5, "description": "Time Limit Exceeded"},
                "stdout": "",
                "exit_code": -1,
                "cpu_time_ms": 2000,
                "wall_time_ms": 4000,
                "memory_kb": 8192,
            }
        ],
    }

    adapter = CitronAdapter(
        citron_url="http://citron.test", transport=_fake_citron_transport(citron_response)
    )
    request = ExecutionRequest(
        language=Language.PYTHON,
        code="while True: pass",
        test_cases=[ExecutionTestCase(id="t0", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in adapter.execute(request)]
    assert results[0].status == ExecutionStatus.TIMEOUT
    assert results[0].status_description == "Time Limit Exceeded"


async def test_execute_maps_runtime_error_segfault() -> None:
    # Live-verified wire id 7 = SIGSEGV.
    citron_response = {
        "id": "abc123",
        "status": {"id": 7, "description": "Runtime Error (SIGSEGV)"},
        "compile": {"skipped": True, "success": True, "output": "", "duration_ms": 0, "cached": False},
        "wall_time_ms": 10,
        "testcases": [
            {
                "index": 0,
                "status": {"id": 7, "description": "Runtime Error (SIGSEGV)"},
                "stdout": "",
                "signal": 11,
                "exit_code": 0,
                "cpu_time_ms": 5,
                "wall_time_ms": 6,
                "memory_kb": 2048,
            }
        ],
    }

    adapter = CitronAdapter(
        citron_url="http://citron.test", transport=_fake_citron_transport(citron_response)
    )
    request = ExecutionRequest(
        language=Language.C,
        code="int main(){int *p=0;*p=1;return 0;}",
        test_cases=[ExecutionTestCase(id="t0", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in adapter.execute(request)]
    assert results[0].status == ExecutionStatus.ERROR
    assert results[0].signal == 11


async def test_execute_reports_compile_failure_for_all_testcases() -> None:
    citron_response = {
        "id": "abc123",
        "status": {"id": 6, "description": "Compilation Error"},
        "compile": {
            "skipped": False,
            "success": False,
            "output": "error: expected ';' before '}'",
            "duration_ms": 100,
            "cached": False,
        },
        "wall_time_ms": 100,
        "testcases": [],
    }

    adapter = CitronAdapter(
        citron_url="http://citron.test", transport=_fake_citron_transport(citron_response)
    )
    request = ExecutionRequest(
        language=Language.CPP,
        code="int main() {",
        test_cases=[ExecutionTestCase(id="t0", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in adapter.execute(request)]
    assert results[0].status == ExecutionStatus.ERROR
    assert "expected ';'" in (results[0].error or "")


async def test_execute_falls_back_to_citron_message_when_stderr_is_empty() -> None:
    # `message` is Citron's own "why did this citron-level failure happen" field — a
    # killed/OOM'd process often never gets the chance to write to stderr itself, so
    # this is frequently the only signal available for what actually went wrong.
    citron_response = {
        "id": "abc123",
        "status": {"id": 13, "description": "Internal Error"},
        "compile": {"skipped": True, "success": True, "output": "", "duration_ms": 0, "cached": False},
        "wall_time_ms": 500,
        "testcases": [
            {
                "index": 0,
                "status": {"id": 13, "description": "Internal Error"},
                "stdout": "",
                "stderr": "",
                "message": "sandbox setup failed",
                "exit_code": -9,
                "cpu_time_ms": 100,
                "wall_time_ms": 500,
                "memory_kb": 0,
            }
        ],
    }

    adapter = CitronAdapter(
        citron_url="http://citron.test", transport=_fake_citron_transport(citron_response)
    )
    request = ExecutionRequest(
        language=Language.PYTHON,
        code="print(1)",
        test_cases=[ExecutionTestCase(id="t0", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in adapter.execute(request)]
    assert results[0].status == ExecutionStatus.ERROR
    assert results[0].error == "sandbox setup failed"


async def test_execute_passes_through_infra_detail_fields() -> None:
    citron_response = {
        "id": "abc123",
        "status": {"id": 4, "description": "Wrong Answer"},
        "compile": {"skipped": True, "success": True, "output": "", "duration_ms": 0, "cached": False},
        "wall_time_ms": 20,
        "testcases": [
            {
                "index": 0,
                "status": {"id": 4, "description": "Wrong Answer"},
                "stdout": "6",
                "stderr": "",
                "exit_code": 0,
                "signal": 0,
                "cpu_time_ms": 12,
                "wall_time_ms": 18,
                "memory_kb": 9001,
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
        ],
    }

    adapter = CitronAdapter(
        citron_url="http://citron.test", transport=_fake_citron_transport(citron_response)
    )
    request = ExecutionRequest(
        language=Language.PYTHON,
        code="print(6)",
        test_cases=[ExecutionTestCase(id="t0", input="", output_hash=hash_output("6"))],
    )

    results = [result async for result in adapter.execute(request)]
    assert results[0].exit_code == 0
    assert results[0].memory_kb == 9001
    assert results[0].status_description == "Wrong Answer"
