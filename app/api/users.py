import secrets
import string
from fastapi import APIRouter, Depends, Query, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User

router = APIRouter()


def _generate_user_id(length: int = 64) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@router.get("/me")
async def get_or_create_user(
    response: Response,
    user_id: str | None = Cookie(default=None, alias="user_id"),
    stored_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    # 1. Cookie still valid — fast path
    if user_id:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            # Sync localStorage if somehow missing
            return {"user_id": user.id, "created_at": user.created_at}

    # 2. Cookie missing/invalid but localStorage has a stored_id
    #    Use it to find or recreate the same user (survives container restarts)
    candidate_id = stored_id if stored_id and len(stored_id) <= 64 else None

    if candidate_id:
        result = await db.execute(select(User).where(User.id == candidate_id))
        user = result.scalar_one_or_none()
        if user:
            # User already in DB (restored from backup or pre-existing)
            _set_cookie(response, user.id)
            return {"user_id": user.id, "created_at": user.created_at}
        else:
            # DB empty (post-restart before restore) — recreate with same ID
            user = User(id=candidate_id)
            db.add(user)
            await db.commit()
            _set_cookie(response, user.id)
            return {"user_id": user.id, "created_at": user.created_at}

    # 3. No cookie, no stored_id — brand new user
    new_id = _generate_user_id()
    user = User(id=new_id)
    db.add(user)
    await db.commit()
    _set_cookie(response, new_id)
    return {"user_id": new_id, "created_at": user.created_at}


def _set_cookie(response: Response, user_id: str):
    response.set_cookie(
        key="user_id",
        value=user_id,
        max_age=365 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
