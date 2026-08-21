from fastapi.responses import StreamingResponse
from fastapi import APIRouter

from app.execution.application.services import ExecutionService
from app.execution.domain.models import ExecutionRequest
from app.execution.infrastructure.existing_sandbox_adapter import ExistingSandboxAdapter

router = APIRouter(prefix="/execution", tags=["execution"])


def get_service() -> ExecutionService:
    return ExecutionService(ExistingSandboxAdapter())


@router.post("/run")
async def run(request: ExecutionRequest) -> StreamingResponse:
    service = get_service()

    async def event_stream():
        async for result in service.run(request):
            yield f"data: {result.model_dump_json()}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
