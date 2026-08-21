import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.execution.application.services import ExecutionService
from app.execution.domain.models import ExecutionRequest
from app.execution.infrastructure.composite_executor import CompositeExecutor

router = APIRouter(prefix="/execution", tags=["execution"])


def get_service() -> ExecutionService:
    return ExecutionService(CompositeExecutor())


@router.post("/run")
async def run(request: ExecutionRequest) -> StreamingResponse:
    service = get_service()

    async def event_stream():
        async for result in service.run(request):
            yield f"data: {result.model_dump_json()}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class LanguageInfo(BaseModel):
    id: str
    name: str
    version: str | None
    installed: bool


async def _detect_version(*args: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
    except OSError:
        return None
    output = (stdout or stderr).decode(errors="replace").strip()
    return output.split("\n")[0] if output else None


@router.get("/languages")
async def languages() -> list[LanguageInfo]:
    node_version = await _detect_version("node", "--version")
    python_version = await _detect_version("python3", "--version") or await _detect_version(
        "python", "--version"
    )
    gcc_version = await _detect_version("gcc", "--version")
    gpp_version = await _detect_version("g++", "--version")
    java_version = await _detect_version("java", "-version")

    return [
        LanguageInfo(
            id="javascript", name="JavaScript (Node.js)", version=node_version, installed=node_version is not None
        ),
        LanguageInfo(id="python", name="Python 3", version=python_version, installed=python_version is not None),
        LanguageInfo(id="c", name="C", version=gcc_version, installed=gcc_version is not None),
        LanguageInfo(id="cpp", name="C++", version=gpp_version, installed=gpp_version is not None),
        LanguageInfo(id="java", name="Java", version=java_version, installed=java_version is not None),
    ]
