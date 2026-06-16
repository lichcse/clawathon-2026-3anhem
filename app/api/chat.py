import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, AsyncSessionLocal
from app.models import User, Repository, ChatMessage
from app.api.deps import get_current_user
from app.config import get_settings

router = APIRouter()
settings = get_settings()

AVAILABLE_MODELS = [
    {"id": "minimax/minimax-m2.5", "name": "MiniMax M2.5"},
    {"id": "qwen/qwen3-5-27b", "name": "Qwen 3.5 27B"},
    {"id": "google/gemma-4-31b-it", "name": "Gemma 4 31B-IT"},
    {"id": "qwen/qwen3-235b-a22b-instruct-2507", "name": "Qwen 3 235B"},
    {"id": "deepseek/deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
]


class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None


@router.get("/models")
async def list_models():
    return AVAILABLE_MODELS


@router.get("/chat/{repo_id}/history")
async def get_history(
    repo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repository not found")
    if repo.user_id != current_user.id and not repo.is_shared:
        raise HTTPException(403, "Access denied")

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.repo_id == repo_id, ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at)
        .limit(100)
    )
    messages = result.scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "model": m.model,
            "created_at": m.created_at,
        }
        for m in messages
    ]


@router.post("/chat/{repo_id}")
async def chat(
    repo_id: int,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repository not found")
    if repo.user_id != current_user.id and not repo.is_shared:
        raise HTTPException(403, "Access denied")

    model = body.model or settings.DEFAULT_MODEL

    # Save user message
    user_msg = ChatMessage(
        repo_id=repo_id,
        user_id=current_user.id,
        role="user",
        content=body.message,
        model=model,
    )
    db.add(user_msg)
    await db.commit()

    # Get recent history (exclude the message just saved)
    hist_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.repo_id == repo_id, ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(21)
    )
    history = list(reversed(hist_result.scalars().all()))

    async def event_stream():
        full_response = ""
        try:
            from app.services.agent_service import get_agent_response
            async for chunk in get_agent_response(
                message=body.message,
                repo=repo,
                history=history[:-1],  # history without current message
                model=model,
            ):
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
                await asyncio.sleep(0)
        except Exception as e:
            err = f"⚠️ Error: {str(e)}"
            full_response = err
            yield f"data: {json.dumps({'content': err})}\n\n"
        finally:
            async with AsyncSessionLocal() as save_db:
                assistant_msg = ChatMessage(
                    repo_id=repo_id,
                    user_id=current_user.id,
                    role="assistant",
                    content=full_response,
                    model=model,
                )
                save_db.add(assistant_msg)
                await save_db.commit()
            yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/chat/{repo_id}/history")
async def clear_history(
    repo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repository not found")
    if repo.user_id != current_user.id and not repo.is_shared:
        raise HTTPException(403, "Access denied")

    msgs = await db.execute(
        select(ChatMessage).where(
            ChatMessage.repo_id == repo_id,
            ChatMessage.user_id == current_user.id,
        )
    )
    for msg in msgs.scalars().all():
        await db.delete(msg)
    await db.commit()
    return {"ok": True}
