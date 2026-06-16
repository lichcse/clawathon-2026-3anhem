"""POST /api/runs, GET /api/runs/{id}, GET /api/runs/{id}/artifact."""

from __future__ import annotations

import json
import pathlib
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..db.models import Run
from ..db.session import get_session
from ..runner.executor import run_workflow

router = APIRouter(prefix="/api/runs", tags=["runs"])


class WorkflowStep(BaseModel):
    block_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    input_bindings: dict[str, str] = Field(default_factory=dict)


class CandidateBlockDef(BaseModel):
    code: str
    name: str | None = None
    description: str | None = None
    version: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    params_schema: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    workflow: list[WorkflowStep]
    name: str | None = None
    candidate_blocks: dict[str, CandidateBlockDef] = Field(default_factory=dict)
    workflow_id: str | None = None


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TYPE_MIME = {
    "xlsx_file": _XLSX_MIME,
    "csv_file": "text/csv",
}


def _serialize_run(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "inputs": run.inputs,
        "artifacts": run.artifacts,
        "logs": json.loads(run.logs) if run.logs else [],
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.post("")
def create_run(body: RunRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    steps = [s.model_dump() for s in body.workflow]
    candidate_blocks = {k: v.model_dump() for k, v in body.candidate_blocks.items()}
    run = Run(
        workflow_id=body.workflow_id,
        status="running",
        inputs={
            "workflow": steps,
            "name": body.name,
            "candidate_blocks": candidate_blocks,
        },
        artifacts={},
        logs="",
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    result = run_workflow(steps, run_id=run.id, candidate_blocks=candidate_blocks)

    run.status = result["status"]
    run.logs = json.dumps(result.get("logs", []))
    artifacts: dict[str, Any] = {
        "run_dir": result.get("run_dir"),
        "steps": result.get("step_outputs", []),
    }
    step_outputs = result.get("step_outputs", [])
    if result["status"] == "succeeded" and step_outputs:
        final = step_outputs[-1]
        # pick the "primary" final artifact: prefer xlsx/csv files, else first entry
        chosen_key, chosen_path = next(iter(final.items()))
        for k, v in final.items():
            if isinstance(v, str) and v.lower().endswith((".xlsx", ".csv", ".pdf")):
                chosen_key, chosen_path = k, v
                break
        artifacts["final"] = {
            "step": len(step_outputs) - 1,
            "output_name": chosen_key,
            "path": chosen_path,
            "filename": pathlib.Path(chosen_path).name,
        }
    if result.get("error"):
        artifacts["error"] = result["error"]
    run.artifacts = artifacts
    run.finished_at = datetime.utcnow()
    session.add(run)
    session.commit()
    session.refresh(run)

    return _serialize_run(run)


@router.get("/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return _serialize_run(run)


@router.get("/{run_id}/artifact")
def download_artifact(
    run_id: str,
    step: int | None = Query(default=None, description="Step index; defaults to the final step"),
    name: str | None = Query(default=None, description="Output name; defaults to the primary final artifact"),
    session: Session = Depends(get_session),
):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "succeeded":
        raise HTTPException(status_code=409, detail=f"run not in succeeded state (status={run.status})")

    artifacts = run.artifacts or {}
    if step is None and name is None:
        final = artifacts.get("final")
        if not final:
            raise HTTPException(status_code=404, detail="no final artifact recorded for this run")
        path = final["path"]
        filename = final["filename"]
    else:
        steps = artifacts.get("steps", [])
        step_idx = step if step is not None else len(steps) - 1
        if step_idx < 0 or step_idx >= len(steps):
            raise HTTPException(status_code=404, detail=f"step {step_idx} not found")
        outputs = steps[step_idx]
        if name is None:
            chosen_key = next(iter(outputs))
        elif name in outputs:
            chosen_key = name
        else:
            raise HTTPException(status_code=404, detail=f"output {name!r} not in step {step_idx}")
        path = outputs[chosen_key]
        filename = pathlib.Path(path).name

    p = pathlib.Path(path)
    if not p.exists():
        raise HTTPException(status_code=410, detail="artifact file no longer present on disk")

    suffix = p.suffix.lower().lstrip(".")
    mime = _TYPE_MIME.get(f"{suffix}_file", "application/octet-stream")
    if suffix == "xlsx":
        mime = _XLSX_MIME
    elif suffix == "csv":
        mime = "text/csv"
    return FileResponse(path=str(p), media_type=mime, filename=filename)
