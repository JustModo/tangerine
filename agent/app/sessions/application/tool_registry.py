"""The shape of a chat tool: everything about it in one entry.

A tool used to be spread across four places — its declaration in the prompts module, its
availability rule in _tools_for, its read-only-ness as a literal name tuple inside the
follow-up stream, and its handler in an if/else chain. ToolSpec holds all four, so adding
or removing a tool is one edit and none of them can drift apart.

The TOOLS tuple itself lives at the bottom of services.py: it names SessionService methods,
and a registry module importing SessionService while services.py imports the registry would
be circular.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from app.llm.domain.requests import ChatTurn, ToolDeclaration


@dataclass(frozen=True)
class ToolContext:
    """One tool call's inputs. Handlers used to take different subsets of these in different
    orders, which is what made a dispatch table impossible."""

    session_id: str
    args: dict
    history: list[ChatTurn]
    message: str
    existing_plan: bool
    user_id: str | None
    depth: int
    note_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    tool: ToolDeclaration
    handler: Callable[..., AsyncIterator[dict]]
    # (service, existing_plan, user_id) -> bool. Some tools need a collaborator that may not
    # be wired up, and offering one whose handler cannot run is worse than not offering it.
    available: Callable[[Any, bool, str | None], bool]
