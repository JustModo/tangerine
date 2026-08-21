from collections.abc import AsyncIterator
from typing import Protocol

from app.execution.domain.models import ExecutionRequest, TestResult


class CodeExecutor(Protocol):
    def execute(self, request: ExecutionRequest) -> AsyncIterator[TestResult]: ...
