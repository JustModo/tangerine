import sqlite3
from pathlib import Path

import pytest

from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.schemas.curriculum import GeneratedCurriculum, GeneratedCurriculumNode
from app.shared.database import MIGRATIONS_DIR
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
        nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)],
    )
    # only ONE response queued — a second real call would raise AssertionError
    provider = FakeLLMProvider(structured_responses=[result])

    first = await generate_curriculum(provider, "prefix sums", "python", "beginner", cache=cache)
    second = await generate_curriculum(provider, "prefix sums", "python", "beginner", cache=cache)

    assert [n.skill for n in first.nodes] == [n.skill for n in second.nodes]


async def test_lesson_notes_cache_avoids_a_second_llm_call(db_path: str) -> None:
    from app.llm.graphs.lesson_notes import generate_lesson_notes
    from app.llm.schemas.lesson_notes import GeneratedLessonNotes, LessonNoteStep

    cache = SqliteLLMCache(db_path)
    notes = GeneratedLessonNotes(
        steps=[LessonNoteStep(title="The core idea", body_md="Keep a running total.")]
    )
    # only ONE response queued — a second real call would raise AssertionError. This is the
    # token-efficiency guarantee: a skill's notes are written once, ever.
    provider = FakeLLMProvider(structured_responses=[notes])

    first = await generate_lesson_notes(provider, "prefix-sum", "python", "beginner", cache=cache)
    second = await generate_lesson_notes(provider, "prefix-sum", "python", "beginner", cache=cache)

    assert first == second
    assert first.steps[0].title == "The core idea"

