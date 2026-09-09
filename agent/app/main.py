import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.curriculum.api.problem_sessions_router import router as problem_sessions_router
from app.curriculum.api.router import router as curriculum_router
from app.llm.infrastructure.cache import SqliteLLMCache
from app.problems.api.router import router as problems_router
from app.sessions.api.router import router as sessions_router
from app.settings.router import router as settings_router
from app.setup.router import router as setup_router
from app.shared.config import get_settings
from app.shared.database import run_migrations
from app.shared.errors import register_exception_handlers
from app.shared.secrets import get_gemini_api_key
from app.users.api.router import router as users_router
from app.users.infrastructure.sqlite_repository import SqliteUserRepository

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
GIT_SHA_FILE = Path(__file__).resolve().parent.parent / "GIT_SHA"


def _git_sha() -> str:
    return GIT_SHA_FILE.read_text().strip() if GIT_SHA_FILE.is_file() else "unknown"


logging.basicConfig(
    level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s", force=True
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_migrations()
    await SqliteUserRepository().ensure_default_user()
    await SqliteLLMCache().prune()
    yield
    await _probe_client.aclose()


app = FastAPI(title="Tangerine Agent", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(problems_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(curriculum_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(problem_sessions_router, prefix="/api")
app.include_router(setup_router, prefix="/api")
app.include_router(settings_router, prefix="/api")


class HealthResponse(BaseModel):
    status: str
    services: dict[str, bool]
    git_sha: str


_probe_client = httpx.AsyncClient(timeout=3.0)


async def _citron_ready() -> bool:
    settings = get_settings()
    headers = {"X-Judge-Token": settings.citron_auth_token} if settings.citron_auth_token else {}
    try:
        response = await _probe_client.get(f"{settings.citron_url}/ready", headers=headers)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


@app.get("/health")
async def health() -> HealthResponse:
    services = {"citron": await _citron_ready(), "gemini": bool(await get_gemini_api_key())}
    return HealthResponse(
        status="ok" if all(services.values()) else "degraded",
        services=services,
        git_sha=_git_sha(),
    )


if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
