"""Anthropic client wrapper + system prompt builder."""

from __future__ import annotations

import os
from typing import Any

import anthropic
from sqlmodel import Session, select

from ..db.models import Block

MODEL_ID = os.environ.get("BLOCK_CHAT_MODEL", "claude-sonnet-4-6")


def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _format_schema(schema: dict[str, Any]) -> str:
    if not schema:
        return "(none)"
    parts = []
    for name, spec in schema.items():
        if not isinstance(spec, dict):
            parts.append(f"  - {name}")
            continue
        t = spec.get("type", "any")
        req = " (required)" if spec.get("required") else ""
        desc = spec.get("description", "")
        parts.append(f"  - {name}: {t}{req}{f' — {desc}' if desc else ''}")
    return "\n".join(parts)


def build_block_catalog(session: Session) -> str:
    rows = session.exec(select(Block).order_by(Block.id)).all()
    lines: list[str] = []
    for b in rows:
        lines.append(f"### {b.id}  ({b.status})")
        lines.append(f"{b.name} — {b.description}")
        lines.append("params:")
        lines.append(_format_schema(b.params_schema))
        lines.append("inputs:")
        lines.append(_format_schema(b.input_schema))
        lines.append("outputs:")
        lines.append(_format_schema(b.output_schema))
        lines.append("")
    return "\n".join(lines) if lines else "(no blocks registered)"


SYSTEM_PROMPT_PREAMBLE = """You orchestrate data-prep workflows by composing them out of atomic, reusable blocks from a shared registry. The user chats; you propose a workflow (an ordered list of block steps) that, when run by a downstream subprocess runner, produces the user's desired output.

Rules:
1. Prefer blocks from the catalog below. Search the registry with `search_blocks` only if you suspect a relevant block exists that isn't already shown.
2. When you've decided on the chain, call `propose_workflow` exactly once. After that the orchestrator stops — do not continue searching.
3. Each step is `{block_id, params, input_bindings}`. `params` are scalar/structured values the block needs. `input_bindings` map a logical input name to `"<step_idx>.<output_name>"` — for example, the second step consuming the first step's dataframe is `{"data": "0.data"}`. Steps with no inputs (loaders) have an empty `input_bindings`.
4. The user may attach files; each attachment has a server-side absolute `path`. Pass that exact path to the loader block as the relevant param. Do not invent file paths.
5. If the catalog cannot satisfy the request, say so plainly in your text response and do not call `propose_workflow`. (Ad-hoc block generation will be added later.)
6. Keep your text response short — one or two sentences explaining the chain. The diagram displays the steps.
"""


def build_system(session: Session, attachments: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    catalog = build_block_catalog(session)
    attachments_block = ""
    if attachments:
        lines = ["", "## User attachments for this turn", ""]
        for a in attachments:
            lines.append(f"- {a.get('filename', '?')} (server path: {a.get('path')})")
        attachments_block = "\n".join(lines)

    catalog_text = (
        SYSTEM_PROMPT_PREAMBLE
        + "\n## Block catalog (shared registry)\n\n"
        + catalog
    )
    return [
        {
            "type": "text",
            "text": catalog_text,
            "cache_control": {"type": "ephemeral"},
        },
        *([{"type": "text", "text": attachments_block}] if attachments_block else []),
    ]
