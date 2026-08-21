import asyncio
import shutil
import sys
import tempfile
import time
from pathlib import Path

from app.execution.domain.models import ExecutionRequest, ExecutionStatus, TestResult
from app.shared.hashing import hash_output

_TIMEOUT_SECONDS = 5.0


class LocalSubprocessExecutor:
    """CodeExecutor that runs code directly via subprocess — a faithful port of the
    original web/server/services/runner_service.ts (same compile step, 5s per-testcase
    timeout, same C/C++/Java/Python/JS command shapes), for once Node/Express is removed
    from this repo. Swap for CitronAdapter once Citron's real image is buildable — this
    has no real sandbox isolation, only a timeout, same as the code it replaces."""

    async def execute(self, request: ExecutionRequest):
        language = request.language.value
        code_path = Path(request.code_path)
        temp_dir = Path(tempfile.mkdtemp(prefix="tangerine_run_"))

        try:
            command, compile_error = await self._prepare_command(language, code_path, temp_dir)
            if compile_error is not None:
                for test_case in request.test_cases:
                    yield TestResult(
                        id=test_case.id,
                        status=ExecutionStatus.ERROR,
                        input=test_case.input,
                        error=compile_error,
                    )
                return

            for test_case in request.test_cases:
                stdout, stderr, error, is_timeout, duration_ms = await self._run_once(
                    command, test_case.input, temp_dir
                )
                if error:
                    status = ExecutionStatus.ERROR
                elif is_timeout:
                    status = ExecutionStatus.TIMEOUT
                else:
                    status = (
                        ExecutionStatus.PASSED
                        if hash_output(stdout) == test_case.output_hash
                        else ExecutionStatus.FAILED
                    )
                yield TestResult(
                    id=test_case.id,
                    status=status,
                    input=test_case.input,
                    actual_output=stdout,
                    error=(stderr or error) or None,
                    execution_time_ms=f"{duration_ms:.2f}ms" if duration_ms is not None else None,
                )
        except Exception as exc:
            for test_case in request.test_cases:
                yield TestResult(
                    id=test_case.id,
                    status=ExecutionStatus.ERROR,
                    input=test_case.input,
                    error=f"Runner system error: {exc}",
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def _prepare_command(
        self, language: str, code_path: Path, temp_dir: Path
    ) -> tuple[list[str], str | None]:
        if language in ("c", "cpp"):
            compiler = "gcc" if language == "c" else "g++"
            compiled_path = temp_dir / "out"
            proc = await asyncio.create_subprocess_exec(
                compiler,
                str(code_path),
                "-o",
                str(compiled_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                return [], f"Compilation Error: {stderr.decode(errors='replace')}"
            return [str(compiled_path)], None
        if language == "python":
            if sys.platform == "win32":
                return ["py", "-3", "-u", str(code_path)], None
            return ["python3", "-u", str(code_path)], None
        if language == "javascript":
            return ["node", str(code_path)], None
        if language == "java":
            return ["java", str(code_path)], None
        return [], f"Unsupported language: {language}"

    async def _run_once(
        self, command: list[str], input_text: str, cwd: Path
    ) -> tuple[str, str, str | None, bool, float | None]:
        start = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return "", "", str(exc), False, (time.perf_counter() - start) * 1000

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input_text.encode()), timeout=_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "", "", None, True, (time.perf_counter() - start) * 1000

        duration_ms = (time.perf_counter() - start) * 1000
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        error = f"Process exited with code {proc.returncode}" if proc.returncode != 0 else None
        return stdout, stderr, error, False, duration_ms
