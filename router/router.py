"""Hibrit model (ve ajan) yonlendirici.

Karar zinciri (hizlidan yavasa):
  1. KURALLAR      (~0 ms)   QA, acik model istegi, gorsel eki, cok uzun baglam
  2. SINIFLANDIRICI (~15-30 ms) yerel e5 gommesi -> gorev tipi + zorluk (+ ajan)
  3. LLM            guven esigin altindaysa en hizli modele tek JSON sorusu

Guvenilirlik: SESSIZ YEDEK YOK. Pasif model atlanirsa, LLM basarisiz olursa, siniflandirici
hazir degilse bu `warnings` alanina yazilir ve WARNING loglanir. Router yalnizca ajan ve
model KIMLIGI dondurur; arac/onay katmanina erisimi yoktur (riskli islem onayi atlanamaz).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from loguru import logger

from router.classifier import Prediction, TaskClassifier
from router.llm_fallback import LlmRouter
from router.log import RoutingLog
from router.registry import ModelRegistry
from router import rules


@dataclass
class RouteRequest:
    text: str
    context: str = ""
    request_id: str = ""
    hint_model: str | None = None          # ajanin kendi tercihi (agents.json) - ipucu
    pick_agent: bool = False               # ajan da secilsin mi
    agent_name: str | None = None          # ajan zaten biliniyorsa (acik ad) - gorev tipi ondan
    agent_candidates: set[str] | None = None  # ajan secilecekse adaylar (orn. departman ipucu)
    needs_tools: bool = False
    attachments: list[str] = field(default_factory=list)
    forced_task_type: str | None = None    # "qa" -> her zaman guclu model


@dataclass
class RouteDecision:
    request_id: str
    model_id: str
    chain: list[str]
    chain_name: str
    task_type: str
    difficulty: str
    confidence: float
    source: str                     # rule | classifier | llm_fallback | default
    latency_ms: float
    reason: str
    warnings: list[str] = field(default_factory=list)
    fallbacks_used: list[str] = field(default_factory=list)
    scores: dict[str, Any] = field(default_factory=dict)
    rule: str | None = None
    agent: str | None = None
    agent_confidence: float | None = None
    agent_source: str | None = None   # classifier | conductor_llm | explicit
    agent_scores: list[dict[str, Any]] = field(default_factory=list)

    def as_log(self, text: str) -> dict[str, Any]:
        row = asdict(self)
        row["request"] = (text or "")[:200]
        row["latency_ms"] = round(self.latency_ms, 2)
        row["confidence"] = round(self.confidence, 3)
        if self.agent_confidence is not None:
            row["agent_confidence"] = round(self.agent_confidence, 3)
        return row


class Router:
    def __init__(self, registry: ModelRegistry, classifier: TaskClassifier | None = None,
                 llm: LlmRouter | None = None, log: RoutingLog | None = None,
                 agent_departments: dict[str, str] | None = None) -> None:
        self.registry = registry
        self.agent_departments = dict(agent_departments or {})
        self.classifier = classifier
        self.llm = llm
        self.log = log or RoutingLog(None)

    # ------------------------------------------------------------------ ana karar
    async def route(self, req: RouteRequest) -> RouteDecision:
        t0 = time.perf_counter()
        rid = req.request_id or uuid.uuid4().hex[:12]
        warnings: list[str] = []
        text_for_model = req.text if not req.context else f"{req.text}\n{req.context[:500]}"

        hit = rules.match(text=req.text, context=req.context, attachments=req.attachments,
                          forced_task_type=req.forced_task_type, registry=self.registry)

        task_pred = diff_pred = agent_pred = None
        if self.classifier is not None and self.classifier.ready:
            vec = self.classifier.embed(text_for_model)
            task_pred = self.classifier.predict("task_types", vec)
            diff_pred = self.classifier.predict("difficulty", vec)
            if req.pick_agent and "agents" in self.classifier.heads:
                try:
                    agent_pred = self.classifier.predict("agents", vec, allowed=req.agent_candidates)
                except ValueError:
                    agent_pred = None
        elif hit is None or req.pick_agent:
            warnings.append("yerel siniflandirici hazir degil (gomme modeli yuklenmedi)")

        scores = {
            "task_types": task_pred.top() if task_pred else [],
            "difficulty": diff_pred.top() if diff_pred else [],
            "task_confidence": round(task_pred.confidence, 3) if task_pred else None,
            "difficulty_confidence": round(diff_pred.confidence, 3) if diff_pred else None,
        }

        # Gorev tipi ajandan: ajan biliniyorsa (acik ad ya da guvenli yerel secim) onun tipi.
        # Ajan guveni dusukse ajan Conductor'a sorulacak; tip o ajandan gelecegi icin burada
        # gorev tipi icin LLM'e SORULMAZ (deferred).
        override: tuple[str, float, str] | None = None
        deferred = False
        reg = self.registry
        known = req.agent_name or (
            agent_pred.label if agent_pred and agent_pred.confidence >= reg.agent_threshold else None)
        if known:
            mapped = self.agent_task_type(known)
            if mapped and not self._classifier_task_wins(task_pred):
                conf = 1.0 if req.agent_name else float(agent_pred.confidence if agent_pred else 1.0)
                override = (mapped, conf, f"gorev tipi ajandan ({known})")
        elif req.pick_agent and agent_pred is not None:
            deferred = True

        if hit is not None:
            task_type = hit.task_type or (task_pred.label if task_pred else "sohbet")
            difficulty = "zor" if hit.task_type == "qa" else (diff_pred.label if diff_pred else "orta")
            confidence, source, reason = 1.0, "rule", hit.reason
            chain_name, chain = hit.extra.get("chain_name", hit.rule), list(hit.chain)
        else:
            task_type, difficulty, confidence, source, reason = await self._classify(
                req, task_pred, diff_pred, warnings, override=override, deferred=deferred)
            chain_name, chain = self.registry.chain_for(task_type, difficulty)
            reason = f"{reason} -> {chain_name}"

        chain, notes = self._finalize(chain, task_type=task_type, difficulty=difficulty,
                                      hint=req.hint_model, explicit=bool(hit and hit.explicit),
                                      needs_tools=req.needs_tools, warnings=warnings)
        if notes:
            reason = f"{reason}; {notes}"

        decision = RouteDecision(
            request_id=rid, model_id=chain[0], chain=chain, chain_name=chain_name,
            task_type=task_type, difficulty=difficulty, confidence=float(confidence),
            source=source, latency_ms=(time.perf_counter() - t0) * 1000, reason=reason,
            warnings=warnings, scores=scores, rule=hit.rule if hit else None,
        )
        if agent_pred is not None:
            decision.agent = agent_pred.label
            decision.agent_confidence = agent_pred.confidence
            decision.agent_source = "classifier"
            decision.agent_scores = agent_pred.top()
        for warning in warnings:
            logger.bind(event="routing_warning").warning(f"[router {rid}] {warning}")
        return decision

    async def _classify(self, req: RouteRequest, task_pred: Prediction | None, diff_pred: Prediction | None,
                        warnings: list[str], *, override: tuple[str, float, str] | None = None,
                        deferred: bool = False) -> tuple[str, str, float, str, str]:
        reg = self.registry
        if override is not None:
            task_label, task_conf, task_why = override
        elif task_pred is not None:
            task_label, task_conf, task_why = task_pred.label, task_pred.confidence, "siniflandirici"
        else:
            task_label, task_conf, task_why = None, 0.0, ""
        if deferred and task_label:
            task_why = "gorev tipi secilecek ajandan belirlenecek"
        task_ok = task_label is not None and (override is not None or deferred or task_conf >= reg.task_threshold)
        diff_ok = diff_pred is not None and diff_pred.confidence >= reg.difficulty_threshold

        if task_ok and diff_ok:
            confidence = min(task_conf, diff_pred.confidence)
            return (task_label, diff_pred.label, confidence, "classifier",
                    f"{task_why}: {task_label}/{diff_pred.label} (guven {confidence:.2f})")
        if self.llm is not None:
            try:
                verdict = await self.llm.classify(req.text)
                task = task_label if task_ok else verdict.task_type
                diff = diff_pred.label if diff_ok else verdict.difficulty
                unsure = [n for n, ok in (("gorev tipi", task_ok), ("zorluk", diff_ok)) if not ok]
                kept = f"; {task_why}" if task_ok and task_why else ""
                return (task, diff, 0.8, "llm_fallback",
                        f"LLM ({', '.join(unsure)} belirsiz): {task}/{diff}{kept}")
            except Exception as exc:  # noqa: BLE001 - acikca raporlanir
                warnings.append(f"LLM yonlendirmesi basarisiz ({type(exc).__name__}: {str(exc)[:80]})")
        if task_label and diff_pred:
            confidence = min(task_conf, diff_pred.confidence)
            if self.llm is not None:
                warnings.append("dusuk guvenli siniflandirici karari kullanildi")
            return (task_label, diff_pred.label, confidence, "classifier",
                    f"{task_why} (dusuk guven {confidence:.2f}): {task_label}/{diff_pred.label}")
        warnings.append("ne siniflandirici ne LLM karar verebildi -> varsayilan zincir")
        return "sohbet", "orta", 0.0, "default", "varsayilan"

    # ------------------------------------------------------------------ ajan -> gorev tipi
    def agent_task_type(self, agent: str | None) -> str | None:
        return self.registry.task_type_for_agent(agent, self.agent_departments.get(agent or ""))

    def _classifier_task_wins(self, task_pred: Prediction | None) -> bool:
        """Yetenek gerektiren tiplerde (gorsel) emin olan siniflandirici ajan eslemesini ezer."""
        return bool(task_pred and task_pred.label in self.registry.keep_classifier_task_types
                    and task_pred.confidence >= self.registry.task_threshold)

    # ------------------------------------------------------------------ zincir
    def _finalize(self, chain: list[str], *, task_type: str, difficulty: str, hint: str | None,
                  explicit: bool, needs_tools: bool, warnings: list[str]) -> tuple[list[str], str]:
        reg = self.registry
        notes: list[str] = []
        if hint and not explicit:
            chain = [m for m in chain if m != hint]
            chain = [hint, *chain] if difficulty in reg.hint_first_for else [*chain, hint]

        intended = chain[0] if chain else None
        final: list[str] = []
        for model in dict.fromkeys(chain):
            info = reg.get(model)
            if info is not None and not info.active:
                warnings.append(f"{model} PASIF ({info.reason or info.status}) -> zincirden cikarildi")
                continue
            if not reg.allowed(model, hint=hint, task_type=task_type, explicit=explicit):
                notes.append(f"{model} ucret politikasi geregi cikarildi")
                continue
            if needs_tools and info is not None and not info.has("tool_use"):
                notes.append(f"{model} arac cagiramiyor, cikarildi")
                continue
            final.append(model)

        if not final:
            _, default = reg.chain_for("sohbet", "basit")
            final = [m for m in default if reg.is_active(m) and not (reg.get(m) and reg.get(m).paid)]
            warnings.append("uygun model kalmadi -> varsayilan zincire dusuldu")
            if not final:
                final = list(default)
                warnings.append("varsayilan zincirde de aktif model yok; denetlenmemis haliyle kullaniliyor")
        if intended and final[0] != intended and reg.get(intended) and not reg.is_active(intended):
            warnings.append(f"asil secim {intended} erisilemez; {final[0]} kullanilacak (YEDEK)")
        return final, "; ".join(notes)

    def reroute_for_agent(self, decision: RouteDecision, *, agent: str, hint: str | None,
                          needs_tools: bool, source: str, confidence: float | None) -> RouteDecision:
        """Ajan Conductor LLM'i ile degistiyse modeli yeni ajanin ipucuyla yeniden kurar
        (gommeyi tekrar hesaplamadan). Gorev tipi kural yoksa o ajandan alinir."""
        mapped = self.agent_task_type(agent)
        top = (decision.scores.get("task_types") or [{}])[0]
        classifier_wins = (top.get("label") in self.registry.keep_classifier_task_types
                           and (decision.scores.get("task_confidence") or 0) >= self.registry.task_threshold)
        if decision.rule is None and mapped and mapped != decision.task_type and not classifier_wins:
            decision.reason = f"{decision.reason}; gorev tipi ajandan ({agent}): {mapped}"
            decision.task_type = mapped
        if decision.rule is None:
            decision.chain_name, chain = self.registry.chain_for(decision.task_type, decision.difficulty)
        else:  # kural zinciri (gorsel, uzun baglam, acik istek, qa) korunur
            chain = list(decision.chain)
        warnings: list[str] = []
        chain, notes = self._finalize(chain, task_type=decision.task_type, difficulty=decision.difficulty,
                                      hint=hint, explicit=decision.rule == "explicit_model",
                                      needs_tools=needs_tools, warnings=warnings)
        decision.chain, decision.model_id = chain, chain[0]
        decision.agent, decision.agent_source, decision.agent_confidence = agent, source, confidence
        decision.warnings += warnings
        if notes:
            decision.reason = f"{decision.reason}; {notes}"
        for warning in warnings:
            logger.bind(event="routing_warning").warning(f"[router {decision.request_id}] {warning}")
        return decision

    def fallback_for(self, model_id: str) -> str | None:
        """Pasif bir model icin yedek (Stark ekibi kisilikleri). Aktifse None."""
        if self.registry.is_active(model_id):
            return None
        return self.registry.fallback_for(model_id)

    # ------------------------------------------------------------------ kayit
    def record(self, decision: RouteDecision, text: str) -> None:
        self.log.write("decision", decision.as_log(text))
        logger.info(
            f"[router {decision.request_id}] {decision.source}: {decision.task_type}/{decision.difficulty} "
            f"-> {decision.model_id}"
            + (f" | ajan {decision.agent} ({decision.agent_source})" if decision.agent else "")
            + f" ({decision.latency_ms:.1f} ms)"
        )

    def record_done(self, request_id: str, **fields: Any) -> None:
        self.log.write("done", {"request_id": request_id, **fields})
