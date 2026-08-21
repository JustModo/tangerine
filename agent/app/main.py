from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.curriculum.api.problem_sessions_router import router as problem_sessions_router
from app.curriculum.api.router import router as curriculum_router
from app.evaluation.api.router import router as evaluation_router
from app.execution.api.router import router as execution_router
from app.problems.api.router import router as problems_router
from app.sessions.api.router import router as sessions_router
from app.shared.database import run_migrations
from app.shared.errors import register_exception_handlers
from app.users.api.router import router as users_router
from app.users.infrastructure.sqlite_repository import SqliteUserRepository


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_migrations()
    await SqliteUserRepository().ensure_default_user()
    yield


app = FastAPI(title="Tangerine Agent", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(problems_router)
app.include_router(execution_router)
app.include_router(sessions_router)
app.include_router(curriculum_router)
app.include_router(users_router)
app.include_router(evaluation_router)
app.include_router(problem_sessions_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
