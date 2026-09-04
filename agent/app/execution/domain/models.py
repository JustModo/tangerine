from enum import StrEnum

from pydantic import BaseModel

from app.shared.types import Language


class ExecutionStatus(StrEnum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class TestCase(BaseModel):
    id: str
    input: str
    output_hash: str  # sha256 of the expected output, never plaintext


class ExecutionRequest(BaseModel):
    language: Language
    code: str
    test_cases: list[TestCase]


class TestResult(BaseModel):
    id: str
    status: ExecutionStatus
    input: str
    actual_output: str | None = None
    error: str | None = None
    execution_time_ms: str | None = None
    exit_code: int | None = None
    signal: int | None = None
    memory_kb: int | None = None
    status_description: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    compile_failed: bool = False


def parse_runtime_ms(value: str | None) -> float | None:
    """The sandbox reports execution time as a string like '12ms'."""
    if not value:
        return None
    try:
        return float(value.rstrip("ms").strip())
    except ValueError:
        return None
