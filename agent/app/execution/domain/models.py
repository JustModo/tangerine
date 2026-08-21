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
    output_hash: str  # sha256 of expected output — never plaintext, matches the web app's convention


class ExecutionRequest(BaseModel):
    language: Language
    code_path: str
    test_cases: list[TestCase]


class TestResult(BaseModel):
    id: str
    status: ExecutionStatus
    input: str
    actual_output: str | None = None
    error: str | None = None
    execution_time_ms: str | None = None
