from typing import Protocol

from app.problems.domain.models import Problem, ProblemCriteria
from app.shared.types import Language


class ProblemRepository(Protocol):
    async def get(self, problem_id: str) -> Problem | None: ...

    async def get_many(self, problem_ids: list[str]) -> dict[str, Problem]: ...

    async def find_suitable(self, criteria: ProblemCriteria) -> Problem | None: ...

    async def save(self, problem: Problem) -> None: ...

    async def list_all(
        self, page: int, page_size: int, query: str | None = None, language: str | None = None
    ) -> tuple[list[Problem], int]: ...

    async def list_titles(self, skill_id: str, language: Language) -> list[str]: ...
