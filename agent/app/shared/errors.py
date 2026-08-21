from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AgentError(Exception):
    """Base class for domain-level errors raised by the agent service."""


class NotFoundError(AgentError):
    """Raised when a requested entity does not exist."""


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def _not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(AgentError)
    async def _agent_error(_request: Request, exc: AgentError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": str(exc)})
