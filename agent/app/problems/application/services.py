from app.problems.domain.models import Problem, ProblemCriteria
from app.problems.domain.repository import ProblemRepository


class ProblemSelectionService:
    """Bank lookup only. Generation lives in ProblemValidationService; callers that need
    a fallback chain it themselves (see ProblemSessionService._select_or_generate)."""

    def __init__(self, repository: ProblemRepository) -> None:
        self._repository = repository

    async def find_suitable(self, criteria: ProblemCriteria) -> Problem | None:
        return await self._repository.find_suitable(criteria)

    async def get(self, problem_id: str) -> Problem | None:
        return await self._repository.get(problem_id)
