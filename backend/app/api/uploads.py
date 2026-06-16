"""POST /api/uploads — accept a file, stash it on disk, return a path the runner can use."""

from __future__ import annotations

import pathlib
import re
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UPLOAD_ROOT = pathlib.Path("/tmp/block-chat-uploads")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    base = pathlib.Path(name).name or "upload"
    return _SAFE_NAME.sub("_", base) or "upload"


@router.post("")
async def upload(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    upload_id = str(uuid.uuid4())
    safe = _safe_filename(file.filename)
    dest = UPLOAD_ROOT / f"{upload_id}__{safe}"
    content = await file.read()
    dest.write_bytes(content)
    return {
        "id": upload_id,
        "filename": file.filename,
        "path": str(dest),
        "size": len(content),
        "content_type": file.content_type,
    }
