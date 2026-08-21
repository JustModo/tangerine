from app.execution.domain.models import ExecutionRequest, ExecutionStatus
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.execution.infrastructure.local_subprocess_executor import LocalSubprocessExecutor
from app.shared.hashing import hash_output
from app.shared.types import Language


async def test_execute_runs_real_python_and_hashes_correctly() -> None:
    executor = LocalSubprocessExecutor()
    request = ExecutionRequest(
        language=Language.PYTHON,
        code="print(sum(int(x) for x in input().split()))",
        test_cases=[
            ExecutionTestCase(id="t1", input="1 2 3", output_hash=hash_output("6")),
            ExecutionTestCase(id="t2", input="10 20", output_hash=hash_output("wrong")),
        ],
    )

    results = [result async for result in executor.execute(request)]

    assert results[0].status == ExecutionStatus.PASSED
    assert results[0].exit_code == 0
    assert results[0].signal is None
    assert results[1].status == ExecutionStatus.FAILED
    assert results[1].actual_output.strip() == "30"


async def test_execute_reports_timeout() -> None:
    executor = LocalSubprocessExecutor()
    request = ExecutionRequest(
        language=Language.PYTHON,
        code="import time\ntime.sleep(30)",
        test_cases=[ExecutionTestCase(id="t1", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in executor.execute(request)]
    assert results[0].status == ExecutionStatus.TIMEOUT
    assert results[0].memory_kb is None


async def test_execute_reports_nonzero_exit_code() -> None:
    executor = LocalSubprocessExecutor()
    request = ExecutionRequest(
        language=Language.PYTHON,
        code="import sys\nsys.exit(3)",
        test_cases=[ExecutionTestCase(id="t1", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in executor.execute(request)]
    assert results[0].status == ExecutionStatus.ERROR
    assert results[0].exit_code == 3
    assert results[0].signal is None


async def test_execute_reports_compile_error_for_broken_cpp() -> None:
    executor = LocalSubprocessExecutor()
    request = ExecutionRequest(
        language=Language.CPP,
        code="int main() {",  # unterminated — real compile failure
        test_cases=[ExecutionTestCase(id="t1", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in executor.execute(request)]
    assert results[0].status == ExecutionStatus.ERROR
    assert "Compilation Error" in (results[0].error or "")
