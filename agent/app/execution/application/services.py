from collections.abc import AsyncIterator

from app.execution.domain.executor import CodeExecutor
from app.execution.domain.models import ExecutionRequest, TestResult


class ExecutionService:
    def __init__(self, executor: CodeExecutor) -> None:
        self._executor = executor

    def run(self, request: ExecutionRequest) -> AsyncIterator[TestResult]:
        return self._executor.execute(request)
