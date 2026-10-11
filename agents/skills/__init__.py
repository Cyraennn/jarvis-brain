"""Deterministik yetenek (skill) implementasyonlari.

`AgentSpec.skill` bir anahtar verirse, ajan LLM'den once bu callable'i calistirir,
sonra ciktisini LLM'e ozetletir.
"""

from __future__ import annotations

from typing import Any, Callable

from agents.skills.markdown_auditor import audit_markdown

SKILLS: dict[str, Callable[..., dict[str, Any]]] = {
    "markdown_auditor": audit_markdown,
}


def get_skill(name: str) -> Callable[..., dict[str, Any]] | None:
    return SKILLS.get(name)
