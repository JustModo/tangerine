"""One learner's view of the problem bank: what they have solved, failed, flagged or never
seen, and how to find a problem they are describing in prose.

Distinct from ProblemSelectionService, which answers "give me a suitable problem they have
NOT seen" and is blind to history. This one is about history.

Read-only, and thin by design: an entry carries a title and a status, never a statement.
The chat agent is the main caller, and a list of statements would cost more context than
the answer is worth.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.curriculum.domain.problem_session import ProblemSession, ProblemSessionStatus
from app.shared.fuzzy import match_score

Scope = Literal["flagged", "solved", "practised", "attempted", "all"]

# Below this, a match is noise rather than a near-miss. Same value the problem browser uses.
_MATCH_THRESHOLD = 0.5
# Never hand back more than this, whatever the caller asks for. The point of this module is
# to answer a question in a few lines, not to page a bank into a prompt.
MAX_RESULTS = 10
# How much of the ranked bank to pull before filtering a whole-bank search by skill. Well
# clear of MAX_RESULTS so the filter has room, and far short of loading the bank.
_BANK_CANDIDATES = 100


@dataclass(frozen=True)
class LibraryEntry:
    """One problem as it relates to one learner. No statement — see the module docstring."""

    problem_id: str
    title: str
    difficulty: str
    language: str
    skill: str | None
    status: str | None
    flagged: bool


@dataclass(frozen=True)
class LibraryStats:
    solved_total: int
    solved_this_week: int
    best_streak: int


def _matches_scope(session: ProblemSession | None, scope: Scope) -> bool:
    if scope == "all":
        return True
    if session is None:
        return False
    if scope == "flagged":
        return session.flagged
    if scope == "solved":
        return session.status == ProblemSessionStatus.COMPLETED
    if scope == "practised":
        # Solved and failed both count: a problem they submitted and got wrong is the
        # best revision candidate there is.
        return session.status in (
            ProblemSessionStatus.COMPLETED,
            ProblemSessionStatus.SUBMITTED,
        )
    if scope == "attempted":
        return session.status in (
            ProblemSessionStatus.IN_PROGRESS,
            ProblemSessionStatus.SUBMITTED,
        )
    return True


def compute_stats(sessions: list[ProblemSession], states) -> LibraryStats:
    """Shared with the progress endpoint, which has already fetched both lists for its own
    reasons — passing them in keeps one definition of "solved this week" without paying for
    the same two queries twice."""
    completed = [s for s in sessions if s.status == ProblemSessionStatus.COMPLETED]
    week_ago = datetime.now(UTC) - timedelta(days=7)
    return LibraryStats(
        solved_total=len(completed),
        solved_this_week=sum(1 for s in completed if s.updated_at >= week_ago),
        best_streak=max((state.streak for state in states), default=0),
    )


class ProblemLibraryService:
    def __init__(
        self,
        problem_repository,
        session_repository,
        skill_repository,
        mastery_repository=None,
    ) -> None:
        self._problems = problem_repository
        self._sessions = session_repository
        self._skills = skill_repository
        self._mastery = mastery_repository

    async def find(
        self,
        user_id: str,
        query: str | None = None,
        scope: Scope = "all",
        skill: str | None = None,
        language: str | None = None,
        limit: int = MAX_RESULTS,
    ) -> list[LibraryEntry]:
        """Problems this learner could be referring to, best match first.

        A user-scoped search starts from their sessions (dozens of rows) rather than the
        whole bank, so "my flagged binary search ones" never pays for a full scan — and,
        more importantly, never loses a match to paging the way filtering after a paged
        bank query would.
        """
        limit = max(1, min(limit, MAX_RESULTS))
        sessions = await self._sessions.list_for_user(user_id)
        # Newest session per problem wins: list_for_user is already ORDER BY updated_at DESC.
        latest: dict[str, ProblemSession] = {}
        for session in sessions:
            latest.setdefault(session.problem_id, session)

        skill_id = await self._resolve_skill(skill) if skill else None

        if scope == "all":
            # The bank's own ranked search already handles the query; ask for a generous
            # slice so the skill filter below still has something to work with.
            problems, _ = await self._problems.list_all(1, _BANK_CANDIDATES, query, language)
        else:
            problems = list((await self._problems.get_many(list(latest))).values())

        skill_names = await self._skills.names()
        entries: list[tuple[float, LibraryEntry]] = []
        for problem in problems:
            session = latest.get(problem.id)
            if not _matches_scope(session, scope):
                continue
            if skill_id is not None and skill_id not in problem.skill_ids:
                continue
            # list_all already applied it for scope="all"; user-scoped candidates come
            # straight off their sessions, so they still need filtering here.
            if language and problem.language.value != language:
                continue

            score = 1.0
            if query and scope != "all":
                # list_all already ranked the "all" case; anything else ranks here.
                haystack = " ".join([problem.title, problem.difficulty, *problem.tags])
                score = match_score(query, haystack)
                if score < _MATCH_THRESHOLD:
                    continue

            skill_name = skill_names.get(problem.skill_ids[0]) if problem.skill_ids else None

            entries.append(
                (
                    score,
                    LibraryEntry(
                        problem_id=problem.id,
                        title=problem.title,
                        difficulty=problem.difficulty,
                        language=problem.language.value,
                        skill=skill_name,
                        status=session.status.value if session else None,
                        flagged=bool(session and session.flagged),
                    ),
                )
            )

        entries.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in entries[:limit]]

    async def stats(self, user_id: str) -> LibraryStats:
        """The numbers the progress screen shows, for a coach that until now could only
        talk about skills and never about how much work the learner had actually done."""
        states = [] if self._mastery is None else await self._mastery.list_for_user(user_id)
        return compute_stats(await self._sessions.list_for_user(user_id), states)

    async def _resolve_skill(self, name: str) -> str | None:
        """A skill the user named in prose to its id. Fuzzy, because they say "graphs" for
        a skill stored as "graph traversal" — and never ensure_skill(), which would CREATE
        a junk skill row for a name that matched nothing."""
        best_id, best_score = None, 0.0
        for skill_id, skill_name in await self._skills.list_all():
            score = match_score(name, skill_name)
            if score > best_score:
                best_id, best_score = skill_id, score
        return best_id if best_score >= _MATCH_THRESHOLD else None
