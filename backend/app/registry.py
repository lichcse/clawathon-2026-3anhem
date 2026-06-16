"""Block registry: scan `app/blocks/<slug>/block.yaml` and upsert into the database."""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from sqlmodel import Session

from .db.models import Block

BLOCKS_ROOT = pathlib.Path(__file__).resolve().parent / "blocks"


def load_block_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    if not BLOCKS_ROOT.exists():
        return specs
    for block_dir in sorted(BLOCKS_ROOT.iterdir()):
        if not block_dir.is_dir():
            continue
        yaml_path = block_dir / "block.yaml"
        main_py = block_dir / "main.py"
        if not (yaml_path.exists() and main_py.exists()):
            continue
        spec = yaml.safe_load(yaml_path.read_text()) or {}
        spec["code_path"] = str(main_py)
        specs.append(spec)
    return specs


def seed_blocks(session: Session) -> int:
    n = 0
    for spec in load_block_specs():
        block_id = spec["id"]
        existing = session.get(Block, block_id)
        fields = {
            "name": spec["name"],
            "description": spec["description"],
            "version": spec.get("version", "0.1.0"),
            "input_schema": spec.get("inputs", {}) or {},
            "output_schema": spec.get("outputs", {}) or {},
            "params_schema": spec.get("params", {}) or {},
            "code_path": spec["code_path"],
            "status": "curated",
        }
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            session.add(Block(id=block_id, **fields))
        n += 1
    session.commit()
    return n
