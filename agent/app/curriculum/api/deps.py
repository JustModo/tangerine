"""Shared FastAPI dependency factories for the curriculum routers.

Both routers need the same fully-wired ProblemSessionService. Building it in each one meant
two byte-identical blocks that had to be kept in step by hand.
"""

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.execution.infrastructure.citron_adapter import CitronAdapter
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.infrastructure.gemini.provider import GeminiProvider
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository


def build_validation_service() -> ProblemValidationService:
    return ProblemValidationService(
        SqliteProblemRepository(),
        GeminiProvider(),
        CitronAdapter(),
        llm_cache=SqliteLLMCache(),
    )


def get_problem_session_service() -> ProblemSessionService:
    return ProblemSessionService(
        SqliteLessonPlanRepository(),
        SqliteProblemSessionRepository(),
        ProblemSelectionService(SqliteProblemRepository()),
        build_validation_service(),
        mastery_repository=SqliteUserSkillStateRepository(),
    )
