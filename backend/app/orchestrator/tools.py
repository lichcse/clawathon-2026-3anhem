"""Anthropic tool-use definitions + handlers for the block orchestrator."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from ..db.models import Block

SEARCH_BLOCKS_TOOL: dict[str, Any] = {
    "name": "search_blocks",
    "description": (
        "Look up blocks from the shared block registry by a natural-language query. "
        "The system prompt already lists every curated block with its description and I/O schema, "
        "so use this only when you need to confirm a block exists with a particular capability "
        "or surface less-prominent matches. Returns at most 5 results."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language query, e.g. 'aggregate by group' or 'write excel file'.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

GENERATE_BLOCK_TOOL: dict[str, Any] = {
    "name": "generate_block",
    "description": (
        "Draft a new candidate block when no existing curated block fits the user's step. "
        "The block must be a small, self-contained Python script that reads its inputs from "
        "the workflow runner contract: it takes --workdir, --params (JSON), --inputs (JSON), "
        "and --outputs (JSON) as CLI flags. It must write outputs to <workdir>/<filename> and "
        "record those paths in the outputs JSON. After generating, reference the new block's id "
        "in propose_workflow. The candidate becomes a promoted shared block only if the user "
        "saves the resulting mini-app."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Snake_case slug (e.g. 'add_size_bucket_column'). Must start with a lowercase letter.",
            },
            "name": {"type": "string", "description": "Human-readable name."},
            "description": {
                "type": "string",
                "description": "One-sentence description of what the block does.",
            },
            "params_schema": {
                "type": "object",
                "description": "Per-param spec ({param: {type, description, required}}).",
            },
            "input_schema": {
                "type": "object",
                "description": "Per-input spec ({input: {type, description, required}}).",
            },
            "output_schema": {
                "type": "object",
                "description": "Per-output spec ({output: {type, description}}).",
            },
            "code": {
                "type": "string",
                "description": (
                    "Full Python source for the block's main.py — must include the argparse CLI "
                    "for --workdir/--params/--inputs/--outputs and write a valid outputs.json. "
                    "Dataframes are passed by parquet path; xlsx files by xlsx path."
                ),
            },
        },
        "required": ["id", "name", "description", "code", "params_schema", "input_schema", "output_schema"],
        "additionalProperties": False,
    },
}

PROPOSE_WORKFLOW_TOOL: dict[str, Any] = {
    "name": "propose_workflow",
    "description": (
        "Commit to a final block-chain workflow. Call this exactly once when you've decided on the chain. "
        "After this tool is called the orchestrator stops; do not search for more blocks afterwards."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "A short, user-facing description of what this workflow will do (1-2 sentences).",
            },
            "steps": {
                "type": "array",
                "description": "Ordered list of block-chain steps.",
                "items": {
                    "type": "object",
                    "properties": {
                        "block_id": {
                            "type": "string",
                            "description": "Slug of a block from the registry (e.g. 'load_csv').",
                        },
                        "params": {
                            "type": "object",
                            "description": "Parameter values for this step. Keys must match the block's params schema.",
                        },
                        "input_bindings": {
                            "type": "object",
                            "description": (
                                "Map of logical input name to '<step_idx>.<output_name>' (e.g. {'data': '0.data'}). "
                                "Only required for steps that take dataframes/files from earlier steps."
                            ),
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "required": ["block_id"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "steps"],
        "additionalProperties": False,
    },
}

TOOLS: list[dict[str, Any]] = [SEARCH_BLOCKS_TOOL, GENERATE_BLOCK_TOOL, PROPOSE_WORKFLOW_TOOL]


def validate_candidate_code(code: str) -> str | None:
    """Return an error message if the code doesn't compile, else None."""
    if not isinstance(code, str) or not code.strip():
        return "code is empty"
    try:
        compile(code, "<candidate_block>", "exec")
    except SyntaxError as e:
        return f"SyntaxError: {e.msg} (line {e.lineno})"
    return None


def search_blocks(session: Session, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Lexical search over the block registry — ranks by token overlap with the query."""
    query_tokens = {t for t in query.lower().split() if t}
    rows = session.exec(select(Block)).all()

    scored: list[tuple[int, Block]] = []
    for b in rows:
        haystack = " ".join([b.id, b.name, b.description]).lower()
        haystack_tokens = set(haystack.replace("_", " ").replace(",", " ").split())
        score = len(query_tokens & haystack_tokens)
        scored.append((score, b))
    scored.sort(key=lambda p: (-p[0], p[1].id))

    out: list[dict[str, Any]] = []
    for score, b in scored[:limit]:
        if score == 0 and out:
            break
        out.append(
            {
                "id": b.id,
                "name": b.name,
                "description": b.description,
                "params": b.params_schema,
                "inputs": b.input_schema,
                "outputs": b.output_schema,
                "match_score": score,
            }
        )
    return out


def validate_workflow(
    session: Session,
    steps: list[dict[str, Any]],
    candidate_ids: set[str] | None = None,
) -> list[str]:
    """Return a list of validation errors (empty list = valid).

    candidate_ids are LLM-drafted block IDs registered in this turn — they're
    accepted even though they don't exist in the database yet.
    """
    errors: list[str] = []
    rows = session.exec(select(Block)).all()
    blocks = {b.id: b for b in rows}
    candidate_ids = candidate_ids or set()

    output_names_by_step: list[set[str]] = []

    for idx, step in enumerate(steps):
        block_id = step.get("block_id")
        if not block_id:
            errors.append(f"step {idx}: missing block_id")
            output_names_by_step.append(set())
            continue
        block = blocks.get(block_id)
        is_candidate = block_id in candidate_ids
        if not block and not is_candidate:
            errors.append(f"step {idx}: unknown block_id {block_id!r}")
            output_names_by_step.append(set())
            continue

        if block:
            params_schema = block.params_schema or {}
            inputs_schema = block.input_schema or {}
            outputs_schema = block.output_schema or {}
        else:
            # Candidate — schema-level checks are lighter; we trust the LLM's declared schema.
            params_schema = {}
            inputs_schema = {}
            outputs_schema = {}

        params = step.get("params") or {}
        for pname, pspec in params_schema.items():
            if isinstance(pspec, dict) and pspec.get("required") and pname not in params:
                errors.append(f"step {idx} ({block_id}): missing required param {pname!r}")

        bindings = step.get("input_bindings") or {}
        for in_name, in_spec in inputs_schema.items():
            if isinstance(in_spec, dict) and in_spec.get("required") and in_name not in bindings:
                errors.append(f"step {idx} ({block_id}): missing required input binding {in_name!r}")

        for in_name, binding in bindings.items():
            if not isinstance(binding, str) or "." not in binding:
                errors.append(
                    f"step {idx} ({block_id}): binding for {in_name!r} must look like '<step_idx>.<output>'; got {binding!r}"
                )
                continue
            src_str, src_out = binding.split(".", 1)
            try:
                src_idx = int(src_str)
            except ValueError:
                errors.append(f"step {idx} ({block_id}): invalid step index in {binding!r}")
                continue
            if src_idx >= idx:
                errors.append(
                    f"step {idx} ({block_id}): binding {binding!r} refers to step {src_idx} which is not earlier"
                )
                continue
            # Only check src output if the producer step is a known curated block.
            prior_outputs = output_names_by_step[src_idx]
            if prior_outputs and src_out not in prior_outputs:
                errors.append(
                    f"step {idx} ({block_id}): step {src_idx} does not produce output {src_out!r}"
                )

        output_names_by_step.append(set(outputs_schema.keys()))

    return errors
