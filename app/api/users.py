import secrets
import string
from fastapi import APIRouter, Depends, Response, Cookie
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
    db: AsyncSession = Depends(get_db),
):
    if user_id:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            return {"user_id": user.id, "created_at": user.created_at}

    new_id = _generate_user_id()
    user = User(id=new_id)
    db.add(user)
    await db.commit()

    response.set_cookie(
        key="user_id",
        value=new_id,
        max_age=365 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return {"user_id": new_id, "created_at": user.created_at}
