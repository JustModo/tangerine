"""Every fully-wired service, built in one place.

Routers used to construct their own. That meant the same CurriculumService and
ProblemSessionService blocks existed byte-identically in two and three files, kept in step
by hand, and a router reaching for a service another slice owned had to restate its whole
dependency tree.
"""

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.application.services import CurriculumService
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.evaluation.application.services import EvaluationService
from app.evaluation.infrastructure.sqlite_repository import SqliteEvaluationRepository
from app.execution.infrastructure.citron_adapter import CitronAdapter
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.infrastructure.gemini.provider import GeminiProvider
from app.mastery.application.services import MasteryService
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.application.library import ProblemLibraryService
from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.application.services import RevisionService
from app.sessions.application.services import SessionService
from app.sessions.infrastructure.sqlite_repository import SqliteSessionRepository


def build_validation_service() -> ProblemValidationService:
    return ProblemValidationService(
        SqliteProblemRepository(),
        GeminiProvider(),
        CitronAdapter(),
        llm_cache=SqliteLLMCache(),
    )


def get_curriculum_service() -> CurriculumService:
    return CurriculumService(
        SqliteLessonPlanRepository(),
        GeminiProvider(),
        llm_cache=SqliteLLMCache(),
        mastery_repository=SqliteUserSkillStateRepository(),
        problem_session_repository=SqliteProblemSessionRepository(),
        problem_repository=SqliteProblemRepository(),
        executor=CitronAdapter(),
    )


def get_problem_session_service() -> ProblemSessionService:
    return ProblemSessionService(
        SqliteLessonPlanRepository(),
        SqliteProblemSessionRepository(),
        ProblemSelectionService(SqliteProblemRepository()),
        build_validation_service(),
        mastery_repository=SqliteUserSkillStateRepository(),
    )


def get_library_service() -> ProblemLibraryService:
    return ProblemLibraryService(
        SqliteProblemRepository(),
        SqliteProblemSessionRepository(),
        SqliteSkillRepository(),
        mastery_repository=SqliteUserSkillStateRepository(),
    )


def get_evaluation_service() -> EvaluationService:
    return EvaluationService(
        SqliteEvaluationRepository(),
        SqliteProblemRepository(),
        CitronAdapter(),
        mastery_service=MasteryService(SqliteUserSkillStateRepository()),
    )


def get_session_service() -> SessionService:
    return SessionService(
        SqliteSessionRepository(),
        GeminiProvider(),
        get_curriculum_service(),
        RevisionService(SqliteUserSkillStateRepository()),
        get_problem_session_service(),
        get_library_service(),
    )


def get_problem_repository() -> SqliteProblemRepository:
    return SqliteProblemRepository()
