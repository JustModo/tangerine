import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Base class for domain-level errors raised by the agent service."""


class NotFoundError(AgentError):
    """Raised when a requested entity does not exist."""


class ConflictError(AgentError):
    """Raised when a request is valid but clashes with the current state — adding a step
    that is already on the plan, say. Distinct from NotFoundError so "you already have
    this" doesn't reach the client dressed as "this doesn't exist"."""


def register_exception_handlers(app: FastAPI) -> None:
    """Every error leaves this app as {"error": "<human-readable sentence>"}.

    FastAPI's own defaults are two other shapes — {"detail": str} for HTTPException and
    {"detail": [{...}]} for validation errors — so without these the client has to sniff
    three envelopes to find out what went wrong."""

    @app.exception_handler(NotFoundError)
    async def _not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(ConflictError)
    async def _conflict(_request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(AgentError)
    async def _agent_error(_request: Request, exc: AgentError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.exception_handler(HTTPException)
    async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(status_code=exc.status_code, content={"error": detail}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", ())[1:]) or "request"
        return JSONResponse(
            status_code=422, content={"error": f"{field}: {first.get('msg', 'is invalid')}"}
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        """Without this, an unexpected failure (a dependency being down, say) escapes as
        Starlette's plain-text "Internal Server Error" — not JSON at all, so the client's
        error parsing finds nothing and shows a useless fallback. The real cause goes to
        the log; the browser gets a sentence."""
        logger.exception("Unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": "Something went wrong on the server. Try again in a moment."},
        )
