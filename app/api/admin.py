"""Admin backup/restore endpoints — protected by SECRET_KEY."""
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import Any

from app.database import get_db
from app.config import get_settings
from app.models import User, Repository, ChatMessage, WebhookEvent

router = APIRouter()
settings = get_settings()

BACKUP_VERSION = 1

_DATETIME_FIELDS = {"created_at"}


def _require_admin(x_admin_secret: str = Header(None)):
    if not x_admin_secret or x_admin_secret != settings.SECRET_KEY:
        raise HTTPException(403, "Forbidden")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _coerce_row(row: dict) -> dict:
    """Parse ISO datetime strings back to datetime objects for SQLAlchemy."""
    out = {}
    for k, v in row.items():
        if k in _DATETIME_FIELDS and isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v)
                out[k] = dt.replace(tzinfo=None)
            except (ValueError, TypeError):
                out[k] = v
        else:
            out[k] = v
    return out


@router.get("/admin/backup")
async def backup(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """Export all application data as JSON. Protect with X-Admin-Secret header."""
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    repos = (await db.execute(select(Repository).order_by(Repository.id))).scalars().all()
    messages = (await db.execute(select(ChatMessage).order_by(ChatMessage.id))).scalars().all()
    events = (await db.execute(select(WebhookEvent).order_by(WebhookEvent.id))).scalars().all()

    return {
        "version": BACKUP_VERSION,
        "users": [_row_to_dict(u) for u in users],
        "repositories": [_row_to_dict(r) for r in repos],
        "chat_messages": [_row_to_dict(m) for m in messages],
        "webhook_events": [_row_to_dict(e) for e in events],
        "counts": {
            "users": len(users),
            "repositories": len(repos),
            "chat_messages": len(messages),
            "webhook_events": len(events),
        },
    }


@router.post("/admin/restore")
async def restore(
    payload: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """Restore all application data from a backup JSON. Idempotent — skips existing rows."""
    if payload.get("version") != BACKUP_VERSION:
        raise HTTPException(400, f"Unsupported backup version: {payload.get('version')}")

    inserted = {"users": 0, "repositories": 0, "chat_messages": 0, "webhook_events": 0}
    skipped = {"users": 0, "repositories": 0, "chat_messages": 0, "webhook_events": 0}

    # Restore users first (referenced by repos and messages)
    for row in payload.get("users", []):
        exists = await db.get(User, row["id"])
        if not exists:
            db.add(User(**{k: v for k, v in _coerce_row(row).items() if hasattr(User, k)}))
            inserted["users"] += 1
        else:
            skipped["users"] += 1

    await db.flush()

    # Restore repositories
    for row in payload.get("repositories", []):
        exists = await db.get(Repository, row["id"])
        if not exists:
            db.add(Repository(**{k: v for k, v in _coerce_row(row).items() if hasattr(Repository, k)}))
            inserted["repositories"] += 1
        else:
            skipped["repositories"] += 1

    await db.flush()

    # Restore chat messages
    for row in payload.get("chat_messages", []):
        exists = await db.get(ChatMessage, row["id"])
        if not exists:
            db.add(ChatMessage(**{k: v for k, v in _coerce_row(row).items() if hasattr(ChatMessage, k)}))
            inserted["chat_messages"] += 1
        else:
            skipped["chat_messages"] += 1

    # Restore webhook events
    for row in payload.get("webhook_events", []):
        exists = await db.get(WebhookEvent, row["id"])
        if not exists:
            db.add(WebhookEvent(**{k: v for k, v in _coerce_row(row).items() if hasattr(WebhookEvent, k)}))
            inserted["webhook_events"] += 1
        else:
            skipped["webhook_events"] += 1

    await db.commit()

    # Reset clone_status for newly inserted repos — directory won't exist on fresh container
    if inserted["repositories"] > 0:
        from app.services.git_service import get_repo_path
        result2 = await db.execute(select(Repository))
        all_repos = result2.scalars().all()
        for r in all_repos:
            if not get_repo_path(r.id).exists():
                r.clone_status = "pending"
        await db.commit()

    # Re-clone any repos that are pending/missing on disk (runs after response is sent)
    from app.services.git_service import clone_all_repos
    background_tasks.add_task(clone_all_repos)

    return {
        "status": "ok",
        "inserted": inserted,
        "skipped": skipped,
    }
