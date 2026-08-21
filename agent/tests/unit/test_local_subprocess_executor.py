from pathlib import Path

from app.execution.domain.models import ExecutionRequest, ExecutionStatus
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.execution.infrastructure.local_subprocess_executor import LocalSubprocessExecutor
from app.shared.hashing import hash_output
from app.shared.types import Language


async def test_execute_runs_real_python_and_hashes_correctly(tmp_path: Path) -> None:
    code_file = tmp_path / "solution.py"
    code_file.write_text("print(sum(int(x) for x in input().split()))")

    executor = LocalSubprocessExecutor()
    request = ExecutionRequest(
        language=Language.PYTHON,
        code_path=str(code_file),
        test_cases=[
            ExecutionTestCase(id="t1", input="1 2 3", output_hash=hash_output("6")),
            ExecutionTestCase(id="t2", input="10 20", output_hash=hash_output("wrong")),
        ],
    )

    results = [result async for result in executor.execute(request)]

    assert results[0].status == ExecutionStatus.PASSED
    assert results[1].status == ExecutionStatus.FAILED
    assert results[1].actual_output.strip() == "30"


async def test_execute_reports_timeout(tmp_path: Path) -> None:
    code_file = tmp_path / "solution.py"
    code_file.write_text("import time\ntime.sleep(30)")

    executor = LocalSubprocessExecutor()
    request = ExecutionRequest(
        language=Language.PYTHON,
        code_path=str(code_file),
        test_cases=[ExecutionTestCase(id="t1", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in executor.execute(request)]
    assert results[0].status == ExecutionStatus.TIMEOUT


async def test_execute_reports_compile_error_for_broken_cpp(tmp_path: Path) -> None:
    code_file = tmp_path / "solution.cpp"
    code_file.write_text("int main() {")  # unterminated — real compile failure

    executor = LocalSubprocessExecutor()
    request = ExecutionRequest(
        language=Language.CPP,
        code_path=str(code_file),
        test_cases=[ExecutionTestCase(id="t1", input="", output_hash=hash_output("x"))],
    )

    results = [result async for result in executor.execute(request)]
    assert results[0].status == ExecutionStatus.ERROR
    assert "Compilation Error" in (results[0].error or "")
