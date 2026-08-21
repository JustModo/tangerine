import json
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from watchfiles import Change, awatch

router = APIRouter(prefix="/workspace", tags=["workspace"])


class FileInfo(BaseModel):
    name: str
    path: str
    is_directory: bool


class ListDirectoryResponse(BaseModel):
    files: list[FileInfo]
    current_path: str
    parent: str


def _resolve_directory(path: str | None) -> Path:
    """Mirrors web/server/services/fs_service.ts listDirectory's fallback chain: missing
    path -> home, a file path -> its parent, inaccessible -> home."""
    target = Path(path) if path else Path.home()
    try:
        if not target.is_dir():
            target = target.parent
        if not target.is_dir():
            raise FileNotFoundError
        list(target.iterdir())  # cheap accessibility probe, matches the TS fallback intent
        return target
    except OSError:
        return Path.home()


@router.get("/list")
async def list_directory(path: str | None = Query(default=None)) -> ListDirectoryResponse:
    directory = _resolve_directory(path)

    entries = [
        FileInfo(name=entry.name, path=str(entry), is_directory=entry.is_dir())
        for entry in directory.iterdir()
        if not entry.name.startswith(".")
    ]
    entries.sort(key=lambda f: (not f.is_directory, f.name.lower()))

    return ListDirectoryResponse(
        files=entries, current_path=str(directory), parent=str(directory.parent)
    )


@router.get("/home")
async def get_home() -> dict[str, str]:
    return {"path": str(Path.home())}


@router.get("/watch")
async def watch_file(path: str = Query(...)) -> StreamingResponse:
    async def event_stream():
        try:
            async for changes in awatch(path):
                if not any(kind in (Change.added, Change.modified) for kind, _ in changes):
                    continue
                try:
                    content = Path(path).read_text()
                    yield f"event: change\ndata: {json.dumps({'content': content})}\n\n"
                except OSError as exc:
                    yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
