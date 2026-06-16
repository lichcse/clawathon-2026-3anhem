"""Agentic loop: drive Claude through `search_blocks` / `propose_workflow` tool calls."""

from __future__ import annotations

import json
from typing import Any, Callable

import anthropic
from sqlmodel import Session

from .claude import MODEL_ID, build_system, get_client
from .tools import TOOLS, search_blocks, validate_candidate_code, validate_workflow

MAX_ITERATIONS = 6


def _build_messages(history: list[dict[str, str]], message: str) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    for turn in history:
        role = turn.get("role")
        content = turn.get("content", "")
        if role not in ("user", "assistant") or not content:
            continue
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": message})
    return msgs


def orchestrate(
    *,
    session: Session,
    message: str,
    history: list[dict[str, str]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    client: anthropic.Anthropic | None = None,
) -> dict[str, Any]:
    """Run the tool-use loop for one chat turn.

    Returns:
        {
          "assistant_message": str,                # final text from Claude
          "workflow": list[dict] | None,           # proposed workflow steps (None if not proposed)
          "summary": str | None,                   # summary from propose_workflow tool input
          "tool_trace": list[dict],                # log of tool calls + results
          "validation_errors": list[str],          # if workflow proposed but invalid
          "usage": dict,                           # aggregated token usage
          "stop_reason": str,                      # how the loop ended
        }
    """
    client = client or get_client()
    system = build_system(session, attachments=attachments)
    messages = _build_messages(history or [], message)

    tool_trace: list[dict[str, Any]] = []
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    assistant_text_parts: list[str] = []
    proposed: dict[str, Any] | None = None
    candidate_blocks: dict[str, dict[str, Any]] = {}

    for _iter in range(MAX_ITERATIONS):
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        for k in usage_totals:
            v = getattr(response.usage, k, 0) or 0
            usage_totals[k] += v

        for block in response.content:
            if block.type == "text":
                assistant_text_parts.append(block.text)

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            stop_reason = response.stop_reason or "end_turn"
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results: list[dict[str, Any]] = []
        for tool in tool_uses:
            if tool.name == "search_blocks":
                results = search_blocks(session, query=tool.input.get("query", ""))
                tool_trace.append({"tool": "search_blocks", "input": dict(tool.input), "output": results})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool.id,
                        "content": json.dumps(results),
                    }
                )
            elif tool.name == "generate_block":
                spec = dict(tool.input)
                cand_id = spec.get("id", "")
                err = validate_candidate_code(spec.get("code", ""))
                if err or not cand_id:
                    msg = err or "id is required"
                    tool_trace.append({"tool": "generate_block", "input": spec, "error": msg})
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool.id,
                            "content": json.dumps({"status": "invalid", "error": msg}),
                            "is_error": True,
                        }
                    )
                else:
                    candidate_blocks[cand_id] = {
                        "code": spec["code"],
                        "name": spec.get("name", cand_id),
                        "description": spec.get("description", ""),
                        "params_schema": spec.get("params_schema", {}),
                        "input_schema": spec.get("input_schema", {}),
                        "output_schema": spec.get("output_schema", {}),
                    }
                    tool_trace.append({"tool": "generate_block", "input": {"id": cand_id, "name": spec.get("name")}, "output": "registered"})
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool.id,
                            "content": json.dumps(
                                {"status": "registered", "id": cand_id, "note": "Reference this id in propose_workflow."}
                            ),
                        }
                    )
            elif tool.name == "propose_workflow":
                proposed = dict(tool.input)
                tool_trace.append({"tool": "propose_workflow", "input": proposed})
                errors = validate_workflow(
                    session, proposed.get("steps", []), candidate_ids=set(candidate_blocks)
                )
                if errors:
                    proposed["_validation_errors"] = errors
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool.id,
                            "content": json.dumps(
                                {"status": "invalid", "errors": errors, "note": "fix and call again"}
                            ),
                            "is_error": True,
                        }
                    )
                    proposed = None
                else:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool.id,
                            "content": "Workflow recorded. Reply with a short user-facing confirmation; do not call tools again.",
                        }
                    )
            else:
                tool_trace.append({"tool": tool.name, "input": dict(tool.input), "error": "unknown tool"})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool.id,
                        "content": f"Unknown tool: {tool.name}",
                        "is_error": True,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

        if response.stop_reason == "end_turn":
            stop_reason = "end_turn"
            break
    else:
        stop_reason = "max_iterations"

    workflow = proposed.get("steps") if proposed else None
    summary = proposed.get("summary") if proposed else None
    final_text = "\n".join(s for s in assistant_text_parts if s).strip()
    if not final_text and summary:
        final_text = summary

    return {
        "assistant_message": final_text,
        "workflow": workflow,
        "summary": summary,
        "candidate_blocks": candidate_blocks if workflow else {},
        "tool_trace": tool_trace,
        "usage": usage_totals,
        "stop_reason": stop_reason,
        "validation_errors": [],
    }
