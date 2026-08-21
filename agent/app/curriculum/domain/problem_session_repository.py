from typing import Protocol

from app.curriculum.domain.problem_session import ProblemSession


class ProblemSessionRepository(Protocol):
    async def save(self, session: ProblemSession) -> None: ...

    async def get(self, session_id: str) -> ProblemSession | None: ...

    async def get_by_node(self, lesson_node_id: str) -> ProblemSession | None: ...
