"""Test the orchestrator agentic loop with a stubbed Anthropic client."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import Block
from app.orchestrator.loop import orchestrate
from app.registry import seed_blocks


@dataclasses.dataclass
class FakeText:
    text: str
    type: str = "text"


@dataclasses.dataclass
class FakeToolUse:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclasses.dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclasses.dataclass
class FakeMessage:
    content: list[Any]
    stop_reason: str = "end_turn"
    usage: FakeUsage = dataclasses.field(default_factory=FakeUsage)


class FakeMessagesAPI:
    def __init__(self, scripted_responses: list[FakeMessage]):
        self.scripted = list(scripted_responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.scripted:
            raise RuntimeError("FakeMessagesAPI ran out of scripted responses")
        return self.scripted.pop(0)


class FakeClient:
    def __init__(self, scripted_responses: list[FakeMessage]):
        self.messages = FakeMessagesAPI(scripted_responses)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        seed_blocks(s)
        yield s


def test_orchestrator_returns_text_when_claude_doesnt_call_tools(session):
    client = FakeClient(
        [FakeMessage(content=[FakeText("I'd need more details about the data.")])]
    )
    result = orchestrate(
        session=session,
        message="hi",
        history=[],
        attachments=[],
        client=client,
    )
    assert result["workflow"] is None
    assert "more details" in result["assistant_message"]
    assert result["tool_trace"] == []
    assert result["stop_reason"] == "end_turn"


def test_orchestrator_extracts_valid_workflow(session):
    proposed_steps = [
        {"block_id": "load_csv", "params": {"path": "/tmp/sales.csv"}, "input_bindings": {}},
        {
            "block_id": "export_xlsx",
            "params": {"filename": "out.xlsx"},
            "input_bindings": {"data": "0.data"},
        },
    ]
    client = FakeClient(
        [
            FakeMessage(
                content=[
                    FakeText("Let me build that."),
                    FakeToolUse(
                        id="tu_1",
                        name="propose_workflow",
                        input={"summary": "Load CSV then export xlsx", "steps": proposed_steps},
                    ),
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(content=[FakeText("Done — load_csv then export_xlsx.")]),
        ]
    )
    result = orchestrate(
        session=session,
        message="export the CSV to xlsx",
        attachments=[{"filename": "sales.csv", "path": "/tmp/sales.csv"}],
        client=client,
    )
    assert result["workflow"] == proposed_steps
    assert result["summary"] == "Load CSV then export xlsx"
    assert "Done" in result["assistant_message"]
    assert any(t["tool"] == "propose_workflow" for t in result["tool_trace"])


def test_orchestrator_runs_search_then_propose(session):
    proposed_steps = [
        {"block_id": "load_csv", "params": {"path": "/tmp/x.csv"}, "input_bindings": {}},
        {"block_id": "export_xlsx", "params": {}, "input_bindings": {"data": "0.data"}},
    ]
    client = FakeClient(
        [
            FakeMessage(
                content=[
                    FakeToolUse(id="tu_a", name="search_blocks", input={"query": "csv"}),
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(
                content=[
                    FakeText("OK building it."),
                    FakeToolUse(
                        id="tu_b",
                        name="propose_workflow",
                        input={"summary": "csv → xlsx", "steps": proposed_steps},
                    ),
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(content=[FakeText("Workflow ready.")]),
        ]
    )
    result = orchestrate(session=session, message="csv to xlsx", client=client)
    assert result["workflow"] == proposed_steps
    tool_names = [t["tool"] for t in result["tool_trace"]]
    assert tool_names == ["search_blocks", "propose_workflow"]
    search_results = result["tool_trace"][0]["output"]
    assert any(r["id"] == "load_csv" for r in search_results)


def test_orchestrator_registers_candidate_block_then_proposes(session):
    candidate_code = """
import argparse, json, pathlib
ap = argparse.ArgumentParser()
ap.add_argument('--workdir', required=True)
ap.add_argument('--params', required=True)
ap.add_argument('--inputs', required=True)
ap.add_argument('--outputs', required=True)
args = ap.parse_args()
pathlib.Path(args.outputs).write_text(json.dumps({'data': '/tmp/x.parquet'}))
"""
    steps = [
        {"block_id": "load_csv", "params": {"path": "/tmp/x.csv"}, "input_bindings": {}},
        {
            "block_id": "size_bucket",
            "params": {"column": "quantity"},
            "input_bindings": {"data": "0.data"},
        },
    ]
    client = FakeClient(
        [
            FakeMessage(
                content=[
                    FakeToolUse(
                        id="tu_g",
                        name="generate_block",
                        input={
                            "id": "size_bucket",
                            "name": "Add Size Bucket",
                            "description": "Categorize qty as S/M/L.",
                            "code": candidate_code,
                            "params_schema": {"column": {"type": "string", "required": True}},
                            "input_schema": {"data": {"type": "dataframe", "required": True}},
                            "output_schema": {"data": {"type": "dataframe"}},
                        },
                    )
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(
                content=[
                    FakeToolUse(
                        id="tu_p",
                        name="propose_workflow",
                        input={"summary": "load + classify", "steps": steps},
                    )
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(content=[FakeText("Workflow ready.")]),
        ]
    )
    result = orchestrate(session=session, message="classify by qty", client=client)
    assert result["workflow"] == steps
    assert "size_bucket" in result["candidate_blocks"]
    assert "argparse" in result["candidate_blocks"]["size_bucket"]["code"]


def test_orchestrator_rejects_candidate_with_invalid_python(session):
    bad_code = "def "  # syntax error
    valid_code = "import json, argparse, pathlib\nap=argparse.ArgumentParser()\nap.add_argument('--workdir')\nap.add_argument('--params')\nap.add_argument('--inputs')\nap.add_argument('--outputs')\nargs=ap.parse_args()\npathlib.Path(args.outputs).write_text(json.dumps({'data':'/tmp/x'}))"
    steps = [
        {"block_id": "load_csv", "params": {"path": "/tmp/x.csv"}, "input_bindings": {}},
        {
            "block_id": "my_block",
            "params": {},
            "input_bindings": {"data": "0.data"},
        },
    ]
    client = FakeClient(
        [
            FakeMessage(
                content=[
                    FakeToolUse(
                        id="tu_bad",
                        name="generate_block",
                        input={
                            "id": "my_block",
                            "name": "X",
                            "description": "Y",
                            "code": bad_code,
                            "params_schema": {},
                            "input_schema": {"data": {"type": "dataframe", "required": True}},
                            "output_schema": {"data": {"type": "dataframe"}},
                        },
                    )
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(
                content=[
                    FakeToolUse(
                        id="tu_good",
                        name="generate_block",
                        input={
                            "id": "my_block",
                            "name": "X",
                            "description": "Y",
                            "code": valid_code,
                            "params_schema": {},
                            "input_schema": {"data": {"type": "dataframe", "required": True}},
                            "output_schema": {"data": {"type": "dataframe"}},
                        },
                    )
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(
                content=[
                    FakeToolUse(
                        id="tu_prop",
                        name="propose_workflow",
                        input={"summary": "ok", "steps": steps},
                    )
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(content=[FakeText("Built.")]),
        ]
    )
    result = orchestrate(session=session, message="x", client=client)
    assert result["workflow"] == steps
    assert "my_block" in result["candidate_blocks"]
    # tool_trace records both attempts; the first is an error
    gen_traces = [t for t in result["tool_trace"] if t["tool"] == "generate_block"]
    assert len(gen_traces) == 2
    assert "error" in gen_traces[0]


def test_orchestrator_rejects_invalid_workflow(session):
    bad_steps = [
        {"block_id": "does_not_exist", "params": {}, "input_bindings": {}},
    ]
    good_steps = [
        {"block_id": "load_csv", "params": {"path": "/tmp/x.csv"}, "input_bindings": {}},
        {"block_id": "export_xlsx", "params": {}, "input_bindings": {"data": "0.data"}},
    ]
    client = FakeClient(
        [
            FakeMessage(
                content=[
                    FakeToolUse(
                        id="tu_1",
                        name="propose_workflow",
                        input={"summary": "first try", "steps": bad_steps},
                    )
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(
                content=[
                    FakeText("Fixed."),
                    FakeToolUse(
                        id="tu_2",
                        name="propose_workflow",
                        input={"summary": "fixed", "steps": good_steps},
                    ),
                ],
                stop_reason="tool_use",
            ),
            FakeMessage(content=[FakeText("Done.")]),
        ]
    )
    result = orchestrate(session=session, message="do it", client=client)
    assert result["workflow"] == good_steps  # second attempt succeeds
    assert len(result["tool_trace"]) == 2  # both propose calls recorded
