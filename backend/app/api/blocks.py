"""GET /api/blocks — list the block registry."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..db.models import Block
from ..db.session import get_session

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


@router.get("")
def list_blocks(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(Block).order_by(Block.id)).all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "description": b.description,
            "version": b.version,
            "status": b.status,
            "inputs": b.input_schema,
            "params": b.params_schema,
            "outputs": b.output_schema,
        }
        for b in rows
    ]
