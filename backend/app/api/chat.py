"""POST /api/chat — orchestrate a chat turn through Claude tool-use."""

from __future__ import annotations

import os
from typing import Any

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..db.session import get_session
from ..orchestrator.loop import orchestrate

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatTurn(BaseModel):
    role: str
    content: str


class Attachment(BaseModel):
    id: str | None = None
    filename: str
    path: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)


@router.post("")
def chat(req: ChatRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not set on the backend — orchestrator is offline.",
        )
    try:
        result = orchestrate(
            session=session,
            message=req.message,
            history=[t.model_dump() for t in req.history],
            attachments=[a.model_dump() for a in req.attachments],
        )
    except anthropic.AuthenticationError as e:
        raise HTTPException(status_code=503, detail=f"Anthropic auth failed: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"Claude API error ({e.status_code}): {e.message}") from e
    return result
