"""Ajan kayit defteri - kisisel asistan departman hiyerarsisi + istege bagli JSON override."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from agents.departments import DEPARTMENTS, all_agents
from agents.schemas import AgentSpec

__all__ = ["load_agents", "load_orchestrator_config", "DEPARTMENTS", "all_agents"]


def _read_config(config_path: Path | None) -> Any:
    if not config_path or not Path(config_path).is_file():
        return None
    try:
        return json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Ajan config okunamadi ({config_path}): {exc!r}")
        return None


def load_agents(config_path: Path | None = None) -> dict[str, AgentSpec]:
    """6 departmandaki tum ajanlari dondurur; `config_path` varsa ustune JSON override.

    JSON bicimi: [{"name": "...", ...}, ...]  veya  {"agents": [ ... ]}
    """
    agents = all_agents()

    raw = _read_config(config_path)
    if raw is None:
        return agents

    items = raw.get("agents", []) if isinstance(raw, dict) else raw
    loaded = 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        try:
            spec = AgentSpec(**item)
        except Exception as exc:  # noqa: BLE001 - tek bozuk ajan digerlerini engellemesin
            logger.warning(f"Ajan tanimi atlandi ({item.get('name')}): {exc!r}")
            continue
        agents[spec.name] = spec
        loaded += 1
    logger.info(f"Ajan override yuklendi: {config_path} ({loaded} ajan)")
    return agents


def load_orchestrator_config(config_path: Path | None = None) -> dict[str, Any]:
    """agents.json'daki "orchestrator" blogu: {"default_model": .., "fallback_models": [..]}."""
    raw = _read_config(config_path)
    block = raw.get("orchestrator") if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        return {}
    fallbacks = block.get("fallback_models") or []
    return {
        "default_model": str(block.get("default_model") or "").strip() or None,
        "fallback_models": [str(m).strip() for m in fallbacks if str(m).strip()],
    }
