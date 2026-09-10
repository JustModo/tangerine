import json

import aiosqlite

from app.problems.domain.models import (
    Problem,
    ProblemCriteria,
    ProblemExample,
    ProblemStatus,
    ProblemTest,
)
from app.shared.database import connect
from app.shared.errors import ConflictError
from app.shared.fuzzy import match_score
from app.shared.types import Language


def _problem(row: aiosqlite.Row, skill_ids: list[str]) -> Problem:
    examples_raw = json.loads(row["examples_json"] or "[]")
    tests_raw = json.loads(row["tests_json"] or "[]")
    return Problem(
        id=row["id"],
        title=row["title"],
        language=row["language"],
        difficulty=row["difficulty"],
        status=row["status"],
        statement_md=row["statement_md"] or "",
        reference_solution=row["reference_solution"] or "",
        pre_code=row["pre_code"] or "",
        post_code=row["post_code"] or "",
        user_code=row["user_code"] or "",
        constraints=row["constraints"],
        input_format=row["input_format"],
        output_format=row["output_format"],
        hints=json.loads(row["hints_json"] or "[]"),
        examples=[ProblemExample(**e) for e in examples_raw],
        tests=[ProblemTest(**t) for t in tests_raw],
        skill_ids=skill_ids,
        tags=json.loads(row["tags_json"] or "[]"),
        created_at=row["created_at"],
    )


class SqliteProblemRepository:
    """ProblemRepository backed by SQLite. Implements app.problems.domain.repository.ProblemRepository."""

    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path

    async def get(self, problem_id: str) -> Problem | None:
        async with connect(self._database_path) as db:
            cursor = await db.execute("SELECT * FROM problems WHERE id = ?", (problem_id,))
            row = await cursor.fetchone()
            return await self._hydrate(db, row) if row else None

    async def get_many(self, problem_ids: list[str]) -> dict[str, Problem]:
        """Several problems in two queries instead of two per problem."""
        if not problem_ids:
            return {}
        placeholders = ",".join("?" for _ in problem_ids)
        async with connect(self._database_path) as db:
            cursor = await db.execute(f"SELECT * FROM problems WHERE id IN ({placeholders})", problem_ids)
            rows = await cursor.fetchall()
            cursor = await db.execute(
                f"SELECT problem_id, skill_id FROM problem_skills WHERE problem_id IN ({placeholders})",
                problem_ids,
            )
            skills: dict[str, list[str]] = {}
            for skill_row in await cursor.fetchall():
                skills.setdefault(skill_row["problem_id"], []).append(skill_row["skill_id"])

        return {row["id"]: _problem(row, skills.get(row["id"], [])) for row in rows}

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

        query += " WHERE " + " AND ".join(conditions) + " ORDER BY RANDOM() LIMIT 1"

        async with connect(self._database_path) as db:
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return await self._hydrate(db, row) if row else None

    async def list_all(
        self, page: int, page_size: int, query: str | None = None, language: str | None = None
    ) -> tuple[list[Problem], int]:
        """Every AVAILABLE problem ever generated, newest first."""
        async with connect(self._database_path) as db:
            base = "SELECT p.*, p.statement_md AS description FROM problems p WHERE p.status = ?"
            params: list[str] = [ProblemStatus.AVAILABLE.value]
            if language:
                base += " AND p.language = ?"
                params.append(language)
            cursor = await db.execute(base, params)
            rows = await cursor.fetchall()

        if query:
            needle = query.lower().strip()

            def score(row: aiosqlite.Row) -> float:
                haystack = " ".join(
                    [row["title"], row["description"] or "", row["language"], row["tags_json"] or ""]
                )
                return match_score(needle, haystack)

            ranked = sorted(((row, score(row)) for row in rows), key=lambda pair: pair[1], reverse=True)
            threshold = 0.5
            matched = [row for row, s in ranked if s >= threshold]
            rows = matched or [row for row, _ in ranked[:page_size]]
        else:
            rows = sorted(rows, key=lambda row: row["created_at"], reverse=True)

        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]

        async with connect(self._database_path) as db:
            items = [await self._hydrate(db, row) for row in page_rows]
        return items, total

    async def list_titles(self, skill_id: str, language: Language) -> list[str]:
        """Titles already in the bank for a skill."""
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT DISTINCT p.title FROM problems p "
                "JOIN problem_skills ps ON ps.problem_id = p.id "
                "WHERE ps.skill_id = ? AND p.language = ? AND p.status = ?",
                (skill_id, language.value, ProblemStatus.AVAILABLE.value),
            )
            return [row[0] for row in await cursor.fetchall()]

    async def save(self, problem: Problem) -> None:
        """Upserts self-contained problem document."""
        async with connect(self._database_path) as db:
            cursor = await db.execute("SELECT language FROM problems WHERE id = ?", (problem.id,))
            row = await cursor.fetchone()
            if row is not None and row[0] != problem.language.value:
                raise ConflictError(
                    f"Problem {problem.id} is stored as {row[0]}; a problem's language "
                    f"cannot be changed to {problem.language.value}. Generate a new problem "
                    "for the other language instead."
                )

            await db.execute(
                "INSERT INTO problems (id, title, language, difficulty, "
                "status, statement_md, reference_solution, user_code, pre_code, post_code, "
                "constraints, input_format, output_format, hints_json, examples_json, "
                "tests_json, tags_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, difficulty=excluded.difficulty, status=excluded.status, "
                "statement_md=excluded.statement_md, reference_solution=excluded.reference_solution, "
                "user_code=excluded.user_code, pre_code=excluded.pre_code, post_code=excluded.post_code, "
                "constraints=excluded.constraints, input_format=excluded.input_format, "
                "output_format=excluded.output_format, hints_json=excluded.hints_json, "
                "examples_json=excluded.examples_json, tests_json=excluded.tests_json, "
                "tags_json=excluded.tags_json",
                (
                    problem.id,
                    problem.title,
                    problem.language.value,
                    problem.difficulty,
                    problem.status.value,
                    problem.statement_md,
                    problem.reference_solution,
                    problem.user_code,
                    problem.pre_code,
                    problem.post_code,
                    problem.constraints,
                    problem.input_format,
                    problem.output_format,
                    json.dumps(problem.hints),
                    json.dumps([e.model_dump() for e in problem.examples]),
                    json.dumps([t.model_dump() for t in problem.tests]),
                    json.dumps(problem.tags),
                    problem.created_at.isoformat()
                    if hasattr(problem.created_at, "isoformat")
                    else str(problem.created_at),
                ),
            )
            for skill_id in problem.skill_ids:
                await db.execute(
                    "INSERT OR IGNORE INTO problem_skills (problem_id, skill_id) VALUES (?, ?)",
                    (problem.id, skill_id),
                )
            await db.commit()



    async def _hydrate(self, db: aiosqlite.Connection, row: aiosqlite.Row) -> Problem:
        cursor = await db.execute("SELECT skill_id FROM problem_skills WHERE problem_id = ?", (row["id"],))
        skill_rows = await cursor.fetchall()
        return _problem(row, [r["skill_id"] for r in skill_rows])
