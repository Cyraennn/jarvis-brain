"""Orkestrator olay gozlemcisi (arayuz katmani bunu override eder)."""

from __future__ import annotations

from agents.schemas import AgentSpec, TaskUpdate


class OrchestratorObserver:
    """No-op taban. Cagrilar orkestrator thread'inden gelir; implementasyon
    thread-safe olmalidir."""

    def on_agents_loaded(self, agents: list[AgentSpec]) -> None:
        pass

    def on_task(self, update: TaskUpdate) -> None:
        pass

    # human_assisted ajanlar icin onay (bloklayarak cagrilir). Varsayilan: gec.
    def confirm(self, prompt: str) -> bool:
        return True
