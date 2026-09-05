import sqlite3
from pathlib import Path

import pytest

from app.problems.domain.models import Problem, ProblemCriteria, ProblemStatus, ProblemVersion
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
        title="Static Range Sum",
        language=Language.PYTHON,
        difficulty="easy",
        status=ProblemStatus.AVAILABLE,
        tags=["prefix-sum", "arrays"],
        created_at="2026-01-01T00:00:00",
    )
    await repo.save(problem)

    found = await repo.find_suitable(ProblemCriteria(language=Language.PYTHON))
    assert found is not None
    assert found.id == "p1"

    fetched = await repo.get("p1")
    assert fetched is not None
    assert fetched.title == "Static Range Sum"
    assert fetched.tags == ["prefix-sum", "arrays"]


async def test_save_version_then_get_latest_version_round_trips_metadata(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    await repo.save(
        Problem(
            id="p3",
            title="Two Sum",
            language=Language.PYTHON,
            difficulty="easy",
            status=ProblemStatus.AVAILABLE,
            created_at="2026-01-01T00:00:00",
        )
    )
    await repo.save_version(
        ProblemVersion(
            id="v3",
            problem_id="p3",
            version=1,
            statement_md="Find two numbers that sum to target.",
            reference_solution="...",
            user_code="def solve(nums, target): pass",
            pre_code="x = 1",
            post_code="print(x)",
            constraints="1 <= n <= 10^5",
            hints=["Try a hash map.", "Look up target - x as you go."],
            created_at="2026-01-01T00:00:00",
        )
    )

    version = await repo.get_latest_version("p3")
    assert version is not None
    assert version.constraints == "1 <= n <= 10^5"
    assert version.hints == ["Try a hash map.", "Look up target - x as you go."]
    assert version.user_code == "def solve(nums, target): pass"
    assert version.pre_code == "x = 1"
    assert version.post_code == "print(x)"


async def _save_with_version(repo: SqliteProblemRepository, **overrides) -> Problem:
    defaults = {
        "id": "p1",
        "title": "Two Sum",
        "language": Language.PYTHON,
        "difficulty": "easy",
        "status": ProblemStatus.AVAILABLE,
        "tags": ["arrays", "hashing"],
        "created_at": "2026-01-01T00:00:00",
    }
    defaults.update(overrides)
    problem = Problem(**defaults)
    await repo.save(problem)
    await repo.save_version(
        ProblemVersion(
            id=f"v-{problem.id}",
            problem_id=problem.id,
            version=1,
            statement_md=overrides.get("statement_md", "Find two numbers that sum to target."),
            reference_solution="...",
            created_at="2026-01-01T00:00:00",
        )
    )
    return problem


async def test_list_all_paginates_available_problems(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    for i in range(3):
        await _save_with_version(
            repo, id=f"p{i}", created_at=f"2026-01-0{i + 1}T00:00:00"
        )

    page1, total = await repo.list_all(page=1, page_size=2)
    page2, _ = await repo.list_all(page=2, page_size=2)

    assert total == 3
    assert len(page1) == 2
    assert len(page2) == 1
    # Newest first.
    assert page1[0].id == "p2"


async def test_list_all_excludes_unavailable_problems(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    await _save_with_version(repo, id="p1")
    await _save_with_version(repo, id="p2", status=ProblemStatus.GENERATED)

    items, total = await repo.list_all(page=1, page_size=10)

    assert total == 1
    assert [p.id for p in items] == ["p1"]


async def test_list_all_fuzzy_matches_title_over_an_unrelated_problem(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    await _save_with_version(
        repo, id="p1", title="Two Sum", statement_md="Find two numbers."
    )
    await _save_with_version(
        repo, id="p2", title="Binary Tree Traversal", statement_md="Walk a tree."
    )

    items, total = await repo.list_all(page=1, page_size=10, query="two som")

    assert total == 1
    assert items[0].id == "p1"


async def test_list_all_matches_a_tag_even_behind_a_long_problem_statement(db_path: str) -> None:
    # A real statement_md is a full markdown problem write-up - well past the length where
    # difflib.SequenceMatcher's default autojunk heuristic silently breaks substring
    # matching (it starts marking common characters as "junk" once len(haystack) >= 200,
    # which can zero out an otherwise exact match).
    repo = SqliteProblemRepository(db_path)
    long_statement = (
        "Given an array of integers and a target value, find two numbers that sum to the "
        "target using an efficient lookup structure to achieve linear time complexity "
        "across the entire input array, which can be quite large in the worst case. "
    ) * 3
    await _save_with_version(
        repo,
        id="p1",
        title="Two Sum",
        tags=["hash-table", "arrays"],
        statement_md=long_statement,
    )
    await _save_with_version(
        repo,
        id="p2",
        title="Binary Tree Traversal",
        tags=["trees"],
        statement_md="Walk a tree.",
    )

    items, total = await repo.list_all(page=1, page_size=10, query="hash")

    assert total == 1
    assert items[0].id == "p1"


async def test_list_all_filters_by_language(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    await _save_with_version(repo, id="p1", language=Language.PYTHON)
    await _save_with_version(repo, id="p2", language=Language.JAVA)

    items, total = await repo.list_all(page=1, page_size=10, language="java")

    assert total == 1
    assert items[0].id == "p2"


async def test_list_all_falls_back_to_closest_matches_when_nothing_clears_the_threshold(
    db_path: str,
) -> None:
    repo = SqliteProblemRepository(db_path)
    await _save_with_version(
        repo,
        id="p1",
        title="Two Sum",
        tags=["hash-table"],
        statement_md="Find two numbers.",
    )
    await _save_with_version(
        repo,
        id="p2",
        title="Binary Tree Traversal",
        tags=["trees"],
        statement_md="Walk a tree.",
    )

    items, total = await repo.list_all(page=1, page_size=10, query="zzzzzzzzzz")

    # Nothing clears the similarity threshold, but a fuzzy search still returns its best
    # guesses rather than a blank page.
    assert total > 0
    assert len(items) > 0


async def test_find_suitable_excludes_unavailable_and_wrong_language(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    await repo.save(
        Problem(
            id="p2",
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
