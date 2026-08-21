import uuid


from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.domain.models import ProblemCriteria
from app.shared.config import get_settings
from app.shared.database import connect
from app.shared.types import Language


class PrefetchService:
    """Kicks off generation for a likely-next skill in the background, so the bank
    already has a match by the time the user reaches it. generation_jobs
    tracks status and prevents duplicate concurrent generation for the same target."""

    def __init__(
        self,
        problem_selection: ProblemSelectionService,
        problem_validation: ProblemValidationService,
        database_path: str | None = None,
    ) -> None:
        self._problem_selection = problem_selection
        self._problem_validation = problem_validation
        self._database_path = database_path or get_settings().database_path

    async def prefetch(self, skill_id: str, skill_name: str, language: Language, difficulty: str) -> None:
        if await self._already_in_flight(skill_id, language, difficulty):
            return

        criteria = ProblemCriteria(skill_id=skill_id, language=language, difficulty=difficulty)
        existing = await self._problem_selection.find_suitable(criteria)
        if existing is not None:
            return  # bank already covers this — nothing to prefetch

        job_id = str(uuid.uuid4())
        await self._record_job(job_id, skill_id, language, difficulty, status="RUNNING")
        try:
            problem = await self._problem_validation.generate_and_validate(skill_name, language, difficulty)
            status = "SUCCEEDED" if problem is not None else "FAILED"
            await self._update_job(job_id, status, problem_id=problem.id if problem else None)
        except Exception as exc:
            await self._update_job(job_id, "FAILED", error=str(exc))

    async def _already_in_flight(self, skill_id: str, language: Language, difficulty: str) -> bool:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM generation_jobs WHERE skill_id = ? AND language = ? AND difficulty = ? "
                "AND status IN ('RUNNING', 'SUCCEEDED') LIMIT 1",
                (skill_id, language.value, difficulty),
            )
            return await cursor.fetchone() is not None

    async def _record_job(
        self, job_id: str, skill_id: str, language: Language, difficulty: str, status: str
    ) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO generation_jobs (id, skill_id, language, difficulty, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (job_id, skill_id, language.value, difficulty, status),
            )
            await db.commit()

    async def _update_job(
        self, job_id: str, status: str, problem_id: str | None = None, error: str | None = None
    ) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "UPDATE generation_jobs SET status = ?, problem_id = ?, error = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (status, problem_id, error, job_id),
            )
            await db.commit()
