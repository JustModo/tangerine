import json

import aiosqlite

from app.problems.domain.models import (
    Problem,
    ProblemCriteria,
    ProblemExample,
    ProblemStatus,
    ProblemTest,
    ProblemVersion,
)
from app.shared.config import get_settings
from app.shared.database import connect
from app.shared.types import Language


class SqliteProblemRepository:
    """ProblemRepository backed by SQLite. Implements app.problems.domain.repository.ProblemRepository."""

    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def get(self, problem_id: str) -> Problem | None:
        async with connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM problems WHERE id = ?", (problem_id,))
            row = await cursor.fetchone()
            return await self._hydrate(db, row) if row else None

    async def find_suitable(self, criteria: ProblemCriteria) -> Problem | None:
        query = "SELECT DISTINCT p.* FROM problems p"
        conditions = ["p.status = ?"]
        params: list[object] = [ProblemStatus.AVAILABLE.value]

        if criteria.skill_id:
            query += " JOIN problem_skills ps ON ps.problem_id = p.id"
            conditions.append("ps.skill_id = ?")
            params.append(criteria.skill_id)
        if criteria.language:
            conditions.append("p.language = ?")
            params.append(criteria.language.value)
        if criteria.difficulty:
            conditions.append("p.difficulty = ?")
            params.append(criteria.difficulty)
        if criteria.exclude_problem_ids:
            placeholders = ",".join("?" for _ in criteria.exclude_problem_ids)
            conditions.append(f"p.id NOT IN ({placeholders})")
            params.extend(criteria.exclude_problem_ids)

        # RANDOM(), not the first row: without it a skill with several bank problems would
        # serve the same one to everybody forever, and exclude_problem_ids would be the only
        # thing that ever varied the answer.
        query += " WHERE " + " AND ".join(conditions) + " ORDER BY RANDOM() LIMIT 1"

        async with connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return await self._hydrate(db, row) if row else None

    async def list_by_skill(self, skill_id: str) -> list[Problem]:
        async with connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT DISTINCT p.* FROM problems p "
                "JOIN problem_skills ps ON ps.problem_id = p.id "
                "WHERE ps.skill_id = ?",
                (skill_id,),
            )
            rows = await cursor.fetchall()
            return [await self._hydrate(db, row) for row in rows]

    async def find_by_conceptual_id(self, conceptual_id: str, language: Language) -> Problem | None:
        """Duplicate check: two generations for the same skill routinely land on the same
        classic problem, and without this the bank fills with near-identical rows."""
        async with connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM problems WHERE conceptual_id = ? AND language = ? AND status = ? LIMIT 1",
                (conceptual_id, language.value, ProblemStatus.AVAILABLE.value),
            )
            row = await cursor.fetchone()
            return await self._hydrate(db, row) if row else None

    async def list_titles(self, skill_id: str, language: Language) -> list[str]:
        """Titles already in the bank for a skill, fed to the generator as a do-not-repeat
        list so a second problem is actually a second problem."""
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT DISTINCT p.title FROM problems p "
                "JOIN problem_skills ps ON ps.problem_id = p.id "
                "WHERE ps.skill_id = ? AND p.language = ? AND p.status = ?",
                (skill_id, language.value, ProblemStatus.AVAILABLE.value),
            )
            return [row[0] for row in await cursor.fetchall()]

    async def save(self, problem: Problem) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO problems (id, conceptual_id, title, language, difficulty, status, tags_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, difficulty=excluded.difficulty, status=excluded.status, "
                "tags_json=excluded.tags_json",
                (
                    problem.id,
                    problem.conceptual_id,
                    problem.title,
                    problem.language.value,
                    problem.difficulty,
                    problem.status.value,
                    json.dumps(problem.tags),
                    problem.created_at.isoformat(),
                ),
            )
            for skill_id in problem.skill_ids:
                await db.execute(
                    "INSERT OR IGNORE INTO problem_skills (problem_id, skill_id) VALUES (?, ?)",
                    (problem.id, skill_id),
                )
            await db.commit()

    async def save_version(self, version: ProblemVersion) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO problem_versions "
                "(id, problem_id, version, statement_md, reference_solution, user_code, "
                "pre_code, post_code, constraints, hints_json, stress_input, "
                "stress_runtime_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    version.id,
                    version.problem_id,
                    version.version,
                    version.statement_md,
                    version.reference_solution,
                    version.user_code,
                    version.pre_code,
                    version.post_code,
                    version.constraints,
                    json.dumps(version.hints),
                    version.stress_input,
                    version.stress_runtime_ms,
                    version.created_at.isoformat(),
                ),
            )
            for example in version.examples:
                await db.execute(
                    "INSERT INTO problem_examples (id, problem_version_id, input, output, explanation) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (example.id, version.id, example.input, example.output, example.explanation),
                )
            for test in version.tests:
                await db.execute(
                    "INSERT INTO problem_tests (id, problem_version_id, input, output_hash, is_hidden) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (test.id, version.id, test.input, test.output_hash, int(test.is_hidden)),
                )
            await db.commit()

    async def get_latest_version(self, problem_id: str) -> ProblemVersion | None:
        async with connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM problem_versions WHERE problem_id = ? ORDER BY version DESC LIMIT 1",
                (problem_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None

            examples_cursor = await db.execute(
                "SELECT * FROM problem_examples WHERE problem_version_id = ?", (row["id"],)
            )
            example_rows = await examples_cursor.fetchall()
            tests_cursor = await db.execute(
                "SELECT * FROM problem_tests WHERE problem_version_id = ?", (row["id"],)
            )
            test_rows = await tests_cursor.fetchall()

            return ProblemVersion(
                id=row["id"],
                problem_id=row["problem_id"],
                version=row["version"],
                statement_md=row["statement_md"],
                reference_solution=row["reference_solution"],
                user_code=row["user_code"],
                pre_code=row["pre_code"],
                post_code=row["post_code"],
                constraints=row["constraints"],
                hints=json.loads(row["hints_json"] or "[]"),
                stress_input=row["stress_input"],
                stress_runtime_ms=row["stress_runtime_ms"],
                created_at=row["created_at"],
                examples=[
                    ProblemExample(id=e["id"], input=e["input"], output=e["output"], explanation=e["explanation"])
                    for e in example_rows
                ],
                tests=[
                    ProblemTest(
                        id=t["id"], input=t["input"], output_hash=t["output_hash"], is_hidden=bool(t["is_hidden"])
                    )
                    for t in test_rows
                ],
            )

    async def _hydrate(self, db: aiosqlite.Connection, row: aiosqlite.Row) -> Problem:
        cursor = await db.execute("SELECT skill_id FROM problem_skills WHERE problem_id = ?", (row["id"],))
        skill_rows = await cursor.fetchall()
        return Problem(
            id=row["id"],
            conceptual_id=row["conceptual_id"],
            title=row["title"],
            language=row["language"],
            difficulty=row["difficulty"],
            status=row["status"],
            skill_ids=[r["skill_id"] for r in skill_rows],
            tags=json.loads(row["tags_json"] or "[]"),
            created_at=row["created_at"],
        )
