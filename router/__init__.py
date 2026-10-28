"""JARVIS model router: her istekte ajan + model kararini milisaniyeler icinde verir.

Kullanim (agents/orchestrator.py):
    router = build_router(settings, agents=agents, llm_ask=...)
    asyncio.create_task(warm_up(router, settings))   # gomme modeli + model denetimi
    decision = await router.route(RouteRequest(text=..., pick_agent=True))

Kapatmak: JARVIS_ROUTER_ENABLED=false (ya da ROUTER_ENABLED=false).
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from router.classifier import TaskClassifier, load_examples, load_trained
from router.embedder import E5Embedder, Embedder
from router.llm_fallback import AskFn, LlmRouter
from router.log import RoutingLog
from router.registry import ModelInfo, ModelRegistry
from router.router import RouteDecision, RouteRequest, Router

__all__ = [
    "ModelInfo", "ModelRegistry", "RouteDecision", "RouteRequest", "Router",
    "build_router", "get_active", "set_active", "warm_up",
]

_active: Router | None = None


def set_active(router: Router | None) -> None:
    """Surecteki etkin router (Stark ekibi pasif model yedegi icin okur)."""
    global _active
    _active = router


def get_active() -> Router | None:
    return _active


def agent_prototypes(agents: dict[str, Any]) -> dict[str, list[str]]:
    """Her ajan icin prototip metinleri: basligi + aciklamasi (+ examples.yaml'dakiler)."""
    out: dict[str, list[str]] = {}
    for name, spec in agents.items():
        title = str(getattr(spec, "title", "") or "")
        desc = str(getattr(spec, "description", "") or "")
        out[name] = [t for t in (f"{title}: {desc}".strip(": "), desc) if t]
    return out


def build_router(settings: Any, *, agents: dict[str, Any] | None = None, llm_ask: AskFn | None = None,
                 embedder: Embedder | None = None) -> Router:
    registry = ModelRegistry.load(settings.router_config_path)
    examples = load_examples(settings.router_examples_path)
    if agents is not None:
        # yalnizca gercekten yuklu ajanlar aday olabilir
        examples["agents"] = {k: v for k, v in examples.get("agents", {}).items() if k in agents}
    classifier = TaskClassifier(
        embedder or E5Embedder(), examples, temperature=registry.temperature,
        trained=load_trained(getattr(settings, "router_model_path", None)),
    )
    if agents is not None:
        classifier.add_agent_examples(agent_prototypes(agents))
    llm = LlmRouter(llm_ask, task_types=registry.task_types, timeout_s=registry.llm_timeout) if llm_ask else None
    departments = {
        name: (spec.department.value if getattr(spec, "department", None) is not None else "")
        for name, spec in (agents or {}).items()
    }
    return Router(registry, classifier, llm, RoutingLog(settings.routing_log_path), departments)


async def warm_up(router: Router, settings: Any, *, probe: bool = True) -> None:
    """Acilista arka planda: gomme modelini yukle, prototipleri hesapla, modelleri denetle."""
    classifier = router.classifier
    if classifier is not None:
        loader = getattr(classifier.embedder, "load_async", None)
        ok = await loader() if loader else bool(classifier.embedder.ready)
        if ok:
            try:
                await asyncio.to_thread(classifier.fit)
                await asyncio.to_thread(classifier.embed, "isinma")  # ONNX ilk cagri gecikmesi
                logger.success("[router] Yerel siniflandirici hazir (prototipler hesaplandi).")
            except Exception:  # noqa: BLE001
                logger.exception("[router] Siniflandirici hazirlanamadi; kararlar LLM'e sorulacak")
    if probe:
        try:
            await router.registry.probe(
                gemini_key=getattr(settings, "gemini_api_key", "") or "",
                openrouter_key=getattr(settings, "openrouter_api_key", "") or "",
                anthropic_key=getattr(settings, "anthropic_api_key", "") or "",
                anthropic_workspace=getattr(settings, "anthropic_workspace_id", "") or "",
                ollama_url=getattr(settings, "local_llm_url", "http://127.0.0.1:11434"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("[router] Model erisilebilirlik denetimi yapilamadi")
