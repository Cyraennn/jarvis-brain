"""Departman dosyalarinin ortak kisa AgentSpec kurucusu."""

from __future__ import annotations

from agents.schemas import AgentSpec, Autonomy

A = Autonomy


def agent(
    name: str,
    title: str,
    desc: str,
    autonomy: Autonomy,
    sop: str,
    prompt: str,
    *,
    caps: list[str] | None = None,
    grounded: bool = False,
    skills: list[str] | None = None,
    skill: str | None = None,
    temperature: float = 0.4,
    max_steps: int | None = None,
) -> AgentSpec:
    return AgentSpec(
        name=name, title=title, description=desc, autonomy=autonomy, sop=sop,
        system_prompt=prompt, capabilities=caps or [], grounded_search=grounded,
        skills=skills or [], skill=skill, temperature=temperature,
        max_steps=max_steps,
    )
