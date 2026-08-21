import sqlite3
from pathlib import Path

import pytest

from app.problems.domain.models import Problem, ProblemCriteria, ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.database import MIGRATIONS_DIR
from app.shared.types import Language


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


async def test_save_then_find_suitable_and_get(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    problem = Problem(
        id="p1",
        conceptual_id="prefix-sum-range",
        title="Static Range Sum",
        language=Language.PYTHON,
        difficulty="easy",
        status=ProblemStatus.AVAILABLE,
        created_at="2026-01-01T00:00:00",
    )
    await repo.save(problem)

    found = await repo.find_suitable(ProblemCriteria(language=Language.PYTHON))
    assert found is not None
    assert found.id == "p1"

    fetched = await repo.get("p1")
    assert fetched is not None
    assert fetched.title == "Static Range Sum"


async def test_find_suitable_excludes_unavailable_and_wrong_language(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    await repo.save(
        Problem(
            id="p2",
            conceptual_id="two-pointers",
            title="Two Sum Sorted",
            language=Language.PYTHON,
            difficulty="easy",
            status=ProblemStatus.GENERATED,  # not yet AVAILABLE
            created_at="2026-01-01T00:00:00",
        )
    )

    found = await repo.find_suitable(ProblemCriteria(language=Language.PYTHON))
    assert found is None

    found_wrong_lang = await repo.find_suitable(ProblemCriteria(language=Language.CPP))
    assert found_wrong_lang is None
