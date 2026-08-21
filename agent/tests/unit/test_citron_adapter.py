from pathlib import Path

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


async def test_execute_derives_pass_fail_from_our_own_hash_not_citrons_verdict(
    tmp_path: Path,
) -> None:
    # Citron's own status says "Wrong Answer" (id 4) for testcase 0 even though the stdout
    # actually matches our stored hash — the adapter must ignore Citron's verdict and
    # decide PASSED/FAILED itself via hash_output, per the class's whole design intent.
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
    code_file = tmp_path / "solution.py"
    code_file.write_text("print(sum(int(x) for x in input().split()))")

    adapter = CitronAdapter(
        citron_url="http://citron.test", transport=_fake_citron_transport(citron_response)
    )
    request = ExecutionRequest(
        language=Language.PYTHON,
        code_path=str(code_file),
        test_cases=[
            ExecutionTestCase(id="t0", input="1 2 3", output_hash=hash_output("6")),
            ExecutionTestCase(id="t1", input="1 2 3", output_hash=hash_output("6")),
        ],
    )

    results = [result async for result in adapter.execute(request)]

    assert results[0].status == ExecutionStatus.PASSED  # stdout "6" matches our hash
    assert results[1].status == ExecutionStatus.FAILED  # stdout "wrong" does not


async def test_execute_maps_infra_failure_statuses(tmp_path: Path) -> None:
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
    code_file = tmp_path / "solution.py"
    code_file.write_text("while True: pass")

    adapter = CitronAdapter(
        citron_url="http://citron.test", transport=_fake_citron_transport(citron_response)
    )
    request = ExecutionRequest(
        language=Language.PYTHON,
        code_path=str(code_file),
        test_cases=[ExecutionTestCase(id="t0", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in adapter.execute(request)]
    assert results[0].status == ExecutionStatus.TIMEOUT


async def test_execute_reports_compile_failure_for_all_testcases(tmp_path: Path) -> None:
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
    code_file = tmp_path / "solution.cpp"
    code_file.write_text("int main() {")

    adapter = CitronAdapter(
        citron_url="http://citron.test", transport=_fake_citron_transport(citron_response)
    )
    request = ExecutionRequest(
        language=Language.CPP,
        code_path=str(code_file),
        test_cases=[ExecutionTestCase(id="t0", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in adapter.execute(request)]
    assert results[0].status == ExecutionStatus.ERROR
    assert "expected ';'" in (results[0].error or "")
