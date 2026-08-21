import sqlite3
from pathlib import Path

import pytest

from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.schemas.curriculum import GeneratedCurriculum, GeneratedCurriculumNode
from app.problems.application.prefetch import PrefetchService
from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.domain.models import Problem, ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.database import MIGRATIONS_DIR
from app.shared.types import Language
from tests.fakes import FakeLLMProvider


def _apply_migrations(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.executescript(path.read_text())
    conn.commit()
    conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    _apply_migrations(path)
    return path


async def test_llm_cache_avoids_a_second_generation_call(db_path: str) -> None:
    from app.llm.graphs.curriculum import generate_curriculum

    cache = SqliteLLMCache(db_path)
    result = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1)],
    )
    # only ONE response queued — a second real call would raise AssertionError
    provider = FakeLLMProvider(structured_responses=[result])

    first = await generate_curriculum(provider, "prefix sums", "python", "beginner", cache=cache)
    second = await generate_curriculum(provider, "prefix sums", "python", "beginner", cache=cache)

    assert first.title == second.title == "Prefix Sums"


async def test_prefetch_skips_when_bank_already_has_a_match(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    await repo.save(
        Problem(
            id="p1",
            conceptual_id="c1",
            title="Existing",
            language=Language.PYTHON,
            difficulty="easy",
            status=ProblemStatus.AVAILABLE,
            skill_ids=[await SqliteSkillRepository(db_path).ensure_skill("prefix-sum")],
            created_at="2026-01-01T00:00:00",
        )
    )
    skill_id = await SqliteSkillRepository(db_path).ensure_skill("prefix-sum")

    # validation service backed by a provider with NO queued responses — if prefetch tried
    # to generate, this would raise AssertionError, proving it correctly skipped instead.
    validation = ProblemValidationService(
        repo, FakeLLMProvider(), None, SqliteSkillRepository(db_path)  # type: ignore[arg-type]
    )
    prefetch = PrefetchService(ProblemSelectionService(repo), validation, db_path)

    await prefetch.prefetch(skill_id, "prefix-sum", Language.PYTHON, "easy")

    conn = sqlite3.connect(db_path)
    jobs = conn.execute("SELECT status FROM generation_jobs").fetchall()
    conn.close()
    assert jobs == []  # no job was ever recorded — the bank hit short-circuited before that
