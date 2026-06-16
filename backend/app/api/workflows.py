"""POST /api/workflows, GET /api/workflows, GET /api/workflows/{id} — save & list mini-apps.

On save, any `candidate_blocks` referenced by the workflow are promoted: written to
disk under `app/blocks/<id>/` and inserted/updated in the `blocks` table with
`status='promoted'` so they're visible in the shared registry to future chats.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..db.models import Block, Workflow
from ..db.session import get_session
from ..registry import BLOCKS_ROOT

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class CandidateBlockSave(BaseModel):
    code: str
    name: str | None = None
    description: str | None = None
    version: str = "0.1.0"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    params_schema: dict[str, Any] = Field(default_factory=dict)


class WorkflowStep(BaseModel):
    block_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    input_bindings: dict[str, str] = Field(default_factory=dict)


class SaveWorkflowRequest(BaseModel):
    name: str
    description: str = ""
    steps: list[WorkflowStep]
    candidate_blocks: dict[str, CandidateBlockSave] = Field(default_factory=dict)


def _promote_candidate(
    session: Session, block_id: str, defn: CandidateBlockSave
) -> Block:
    """Write the candidate block to disk + upsert into the blocks table."""
    if not _SLUG_RE.match(block_id):
        raise HTTPException(
            status_code=400,
            detail=f"candidate block id {block_id!r} is not a valid slug (lowercase letters/digits/underscore, starts with letter)",
        )

    block_dir = BLOCKS_ROOT / block_id
    block_dir.mkdir(parents=True, exist_ok=True)
    (block_dir / "main.py").write_text(defn.code)
    spec = {
        "id": block_id,
        "name": defn.name or block_id,
        "description": defn.description or "(LLM-generated, promoted by mini-app save)",
        "version": defn.version,
        "inputs": defn.input_schema,
        "params": defn.params_schema,
        "outputs": defn.output_schema,
    }
    (block_dir / "block.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))

    existing = session.get(Block, block_id)
    fields = {
        "name": spec["name"],
        "description": spec["description"],
        "version": defn.version,
        "input_schema": defn.input_schema,
        "output_schema": defn.output_schema,
        "params_schema": defn.params_schema,
        "code_path": str(block_dir / "main.py"),
        "status": "promoted",
    }
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        block = existing
    else:
        block = Block(id=block_id, **fields)
        session.add(block)
    return block


@router.post("")
def save_workflow(
    body: SaveWorkflowRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")

    promoted: list[str] = []
    referenced_ids = {step.block_id for step in body.steps}
    for cand_id, defn in body.candidate_blocks.items():
        if cand_id not in referenced_ids:
            continue
        _promote_candidate(session, cand_id, defn)
        promoted.append(cand_id)

    workflow = Workflow(
        name=body.name.strip(),
        description=body.description,
        steps=[s.model_dump() for s in body.steps],
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)

    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "steps": workflow.steps,
        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        "promoted_blocks": promoted,
    }


@router.get("")
def list_workflows(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(select(Workflow).order_by(Workflow.created_at.desc())).all()
    return [
        {
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "step_count": len(w.steps or []),
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in rows
    ]


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    w = session.get(Workflow, workflow_id)
    if not w:
        raise HTTPException(status_code=404, detail="workflow not found")
    return {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "steps": w.steps,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }
