from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return str(uuid.uuid4())


class Block(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    description: str
    version: str = "0.1.0"
    author: str = "system"
    input_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    output_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    params_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    code_path: str
    status: str = "curated"  # curated | promoted | candidate
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Workflow(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    description: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    source_chat_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Run(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    workflow_id: Optional[str] = Field(default=None, foreign_key="workflow.id")
    status: str = "pending"  # pending | running | succeeded | failed
    inputs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    artifacts: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    logs: str = ""
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None


class CandidateBlock(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    session_id: str
    proposed_for_workflow_id: Optional[str] = None
    name: str
    description: str
    version: str = "0.1.0"
    input_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    output_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    params_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    code: str  # raw python source — promoted to disk on save
    created_at: datetime = Field(default_factory=datetime.utcnow)
