"""Subprocess-based block runner.

A workflow is a list of step dicts:
    {
        "block_id": "load_csv",
        "params": {"path": "..."},
        "input_bindings": {"data": "0.data"},   # logical_input_name -> "<step_idx>.<output_name>"
    }

Each curated block lives at `app/blocks/<block_id>/main.py`. Candidate (LLM-generated)
blocks are passed alongside the workflow as `candidate_blocks` — a dict of
`{block_id: {code, params_schema?, input_schema?, output_schema?, name?, description?}}`.
The runner materializes each candidate to a temp dir on disk before invoking it.

Each block is invoked as:
    python main.py --workdir <dir> --params <file> --inputs <file> --outputs <file>

Inter-step artifacts (parquet, xlsx, ...) are passed by absolute path on disk.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time
import uuid
from typing import Any

import yaml

BLOCKS_ROOT = pathlib.Path(__file__).resolve().parent.parent / "blocks"
RUNS_ROOT = pathlib.Path("/tmp/block-chat-runs")


def _resolve_bindings(
    bindings: dict[str, str], step_outputs: list[dict[str, str]]
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for in_name, binding in bindings.items():
        if "." not in binding:
            raise ValueError(
                f"input_binding for '{in_name}' must look like '<step_idx>.<output_name>', got {binding!r}"
            )
        src_step_str, src_out = binding.split(".", 1)
        try:
            src_step = int(src_step_str)
        except ValueError as e:
            raise ValueError(f"invalid step index in binding {binding!r}") from e
        if src_step >= len(step_outputs):
            raise ValueError(f"binding {binding!r} references step that hasn't run yet")
        if src_out not in step_outputs[src_step]:
            raise ValueError(
                f"binding {binding!r}: step {src_step} did not produce output {src_out!r}"
            )
        resolved[in_name] = step_outputs[src_step][src_out]
    return resolved


def _materialize_candidate(
    run_dir: pathlib.Path, block_id: str, definition: dict[str, Any]
) -> pathlib.Path:
    code = definition.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError(f"candidate block {block_id!r} missing 'code'")
    cand_dir = run_dir / "_candidate_blocks" / block_id
    cand_dir.mkdir(parents=True, exist_ok=True)
    (cand_dir / "main.py").write_text(code)
    spec = {
        "id": block_id,
        "name": definition.get("name", block_id),
        "description": definition.get("description", "(LLM-generated candidate block)"),
        "version": definition.get("version", "0.1.0"),
        "inputs": definition.get("input_schema", {}),
        "params": definition.get("params_schema", {}),
        "outputs": definition.get("output_schema", {}),
    }
    (cand_dir / "block.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    return cand_dir


def run_workflow(
    workflow: list[dict[str, Any]],
    run_id: str | None = None,
    python_exec: str | None = None,
    candidate_blocks: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    run_dir = RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    python_exec = python_exec or sys.executable
    candidates = candidate_blocks or {}

    step_outputs: list[dict[str, str]] = []
    logs: list[dict[str, Any]] = []

    for idx, step in enumerate(workflow):
        block_id = step["block_id"]
        if block_id in candidates:
            try:
                block_dir = _materialize_candidate(run_dir, block_id, candidates[block_id])
            except ValueError as e:
                return {
                    "run_id": run_id,
                    "status": "failed",
                    "failed_at": idx,
                    "error": str(e),
                    "logs": logs,
                    "step_outputs": step_outputs,
                }
        else:
            block_dir = BLOCKS_ROOT / block_id
        main_py = block_dir / "main.py"
        if not main_py.exists():
            return {
                "run_id": run_id,
                "status": "failed",
                "failed_at": idx,
                "error": f"block not found on disk: {block_id}",
                "logs": logs,
                "step_outputs": step_outputs,
            }

        step_dir = run_dir / f"step{idx}"
        step_dir.mkdir(exist_ok=True)
        params_path = step_dir / "params.json"
        inputs_path = step_dir / "inputs.json"
        outputs_path = step_dir / "outputs.json"

        try:
            resolved_inputs = _resolve_bindings(step.get("input_bindings", {}) or {}, step_outputs)
        except ValueError as e:
            return {
                "run_id": run_id,
                "status": "failed",
                "failed_at": idx,
                "error": str(e),
                "logs": logs,
                "step_outputs": step_outputs,
            }

        params_path.write_text(json.dumps(step.get("params", {}) or {}))
        inputs_path.write_text(json.dumps(resolved_inputs))
        outputs_path.write_text("{}")

        cmd = [
            python_exec,
            str(main_py),
            "--workdir",
            str(step_dir),
            "--params",
            str(params_path),
            "--inputs",
            str(inputs_path),
            "--outputs",
            str(outputs_path),
        ]

        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        dt_ms = int((time.time() - t0) * 1000)

        log_entry = {
            "step": idx,
            "block": block_id,
            "returncode": proc.returncode,
            "duration_ms": dt_ms,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "candidate": block_id in candidates,
        }
        logs.append(log_entry)

        if proc.returncode != 0:
            return {
                "run_id": run_id,
                "status": "failed",
                "failed_at": idx,
                "error": f"step {idx} ({block_id}) exited with {proc.returncode}",
                "logs": logs,
                "step_outputs": step_outputs,
            }

        try:
            outs = json.loads(outputs_path.read_text() or "{}")
        except json.JSONDecodeError as e:
            return {
                "run_id": run_id,
                "status": "failed",
                "failed_at": idx,
                "error": f"step {idx} wrote invalid outputs.json: {e}",
                "logs": logs,
                "step_outputs": step_outputs,
            }
        step_outputs.append(outs)

    return {
        "run_id": run_id,
        "status": "succeeded",
        "logs": logs,
        "step_outputs": step_outputs,
        "run_dir": str(run_dir),
    }
