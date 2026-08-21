from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
from app.workspace.api.router import router as workspace_router

# Populated by `pnpm build` in web/ (see web/vite.config.ts's build.outDir) — absent in
# `uvicorn --reload` dev mode, where the Vite dev server (web/) is used instead.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_migrations()
    await SqliteUserRepository().ensure_default_user()
    yield


app = FastAPI(title="Tangerine Agent", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(problems_router, prefix="/api")
app.include_router(execution_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(curriculum_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(evaluation_router, prefix="/api")
app.include_router(problem_sessions_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        # Client-side React Router owns everything not under /api or /assets — always
        # serve index.html and let it route, same as any SPA behind a catch-all.
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
