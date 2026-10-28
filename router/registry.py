"""ModelRegistry: config/models.yaml'daki modeller, zincirler, rotalar ve politika.

Erisilebilirlik kontrolu (`probe`) URETIM istegi gondermez, kota harcamaz: yalnizca
saglayicilarin model listelerine bakar. Erisilemeyen model PASIF isaretlenir ve bu
WARNING ile acikca raporlanir; router pasif modeli zincire koymaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

DIFFICULTIES = ("basit", "orta", "zor")


@dataclass
class ModelInfo:
    id: str
    provider: str
    speed: str = "medium"
    cost: str = "free"
    capabilities: list[str] = field(default_factory=list)
    routable: bool = True
    active: bool = True
    status: str = "denetlenmedi"   # denetlenmedi | erisilebilir | pasif | dogrulanamadi
    reason: str = ""

    @property
    def paid(self) -> bool:
        return self.cost == "paid"

    def has(self, capability: str) -> bool:
        return capability in self.capabilities


class ModelRegistry:
    def __init__(self, data: dict[str, Any]) -> None:
        self.raw = data or {}
        self.models: dict[str, ModelInfo] = {}
        for item in self.raw.get("models", []) or []:
            info = ModelInfo(
                id=str(item["id"]),
                provider=str(item.get("provider", "gemini")),
                speed=str(item.get("speed", "medium")),
                cost=str(item.get("cost", "free")),
                capabilities=list(item.get("capabilities", []) or []),
                routable=bool(item.get("routable", True)),
            )
            self.models[info.id] = info
        self.chains: dict[str, list[str]] = {
            k: [str(m) for m in v] for k, v in (self.raw.get("chains") or {}).items()
        }
        self.routes: dict[str, dict[str, str]] = self.raw.get("routes") or {}
        self.default_chain: str = str(self.raw.get("default_chain", "hizli"))
        self.hint_first_for: set[str] = set(self.raw.get("hint_first_for") or ["orta", "zor"])
        self.aliases: dict[str, str] = {
            str(k).lower(): str(v) for k, v in (self.raw.get("aliases") or {}).items()
        }
        thr = self.raw.get("thresholds") or {}
        self.task_threshold = float(thr.get("task_confidence", 0.75))
        self.difficulty_threshold = float(thr.get("difficulty_confidence", 0.6))
        self.agent_threshold = float(thr.get("agent_confidence", 0.75))
        self.temperature = float(thr.get("margin_temperature", 0.008))
        self.long_context_chars = int(self.raw.get("long_context_chars", 120_000))
        llm = self.raw.get("llm_fallback") or {}
        self.llm_models: list[str] = [str(m) for m in llm.get("models", [])]
        self.llm_timeout = float(llm.get("timeout_s", 6))
        pol = self.raw.get("policy") or {}
        self.paid_task_types: set[str] = set(pol.get("paid_task_types") or ["qa"])
        self.paid_explicit_ok = bool(pol.get("paid_explicit_ok", True))
        self.qa: dict[str, Any] = dict(self.raw.get("qa") or {})
        self.department_task_types: dict[str, str] = {
            str(k): str(v) for k, v in (self.raw.get("department_task_types") or {}).items()}
        self.agent_task_types: dict[str, str] = {
            str(k): str(v) for k, v in (self.raw.get("agent_task_types") or {}).items()}
        self.keep_classifier_task_types: set[str] = set(self.raw.get("keep_classifier_task_types") or [])
        self.pricing: dict[str, dict[str, float]] = {
            str(k): {"input": float(v.get("input", 0)), "output": float(v.get("output", 0))}
            for k, v in (self.raw.get("pricing") or {}).items()}
        est = self.raw.get("cost_estimate") or {}
        self.est_base_input = int(est.get("base_input_tokens", 1500))
        self.est_output = int(est.get("output_tokens", 600))
        self._validate()

    def estimate_cost(self, model: str | None, *, request_chars: int, calls: int = 1) -> float:
        """Bir model kullaniminin TAHMINI dolar maliyeti (token sayisi bilinmez; panoda
        'ESTIMATED' olarak gosterilir). Ucretsiz/bilinmeyen model -> 0."""
        price = self.pricing.get(model or "")
        if not price:
            return 0.0
        calls = max(1, int(calls))
        tokens_in = (request_chars / 4 + self.est_base_input) * calls
        tokens_out = self.est_output * calls
        return round((tokens_in * price["input"] + tokens_out * price["output"]) / 1_000_000, 6)

    def task_type_for_agent(self, agent: str | None, department: str | None) -> str | None:
        """Ajanin gorev tipi: once agent_task_types, yoksa departman eslemesi."""
        if not agent:
            return None
        task = self.agent_task_types.get(agent) or self.department_task_types.get(department or "")
        return task if task in self.routes else None

    # ------------------------------------------------------------------ yukleme
    @classmethod
    def load(cls, path: Path | str) -> ModelRegistry:
        with open(path, encoding="utf-8") as handle:
            return cls(yaml.safe_load(handle) or {})

    def _validate(self) -> None:
        for name, chain in self.chains.items():
            for model in chain:
                if model not in self.models:
                    raise ValueError(f"models.yaml: '{name}' zincirindeki '{model}' models listesinde yok")
        for task, table in self.routes.items():
            for diff, chain in table.items():
                if chain not in self.chains:
                    raise ValueError(f"models.yaml: routes.{task}.{diff} -> bilinmeyen zincir '{chain}'")
        if self.default_chain not in self.chains:
            raise ValueError(f"models.yaml: default_chain '{self.default_chain}' tanimli degil")

    # ------------------------------------------------------------------ sorgular
    @property
    def task_types(self) -> list[str]:
        return list(self.routes)

    def get(self, model_id: str | None) -> ModelInfo | None:
        return self.models.get(model_id or "")

    def is_active(self, model_id: str | None) -> bool:
        """Kayitli degilse (orn. agents.json'daki bilinmeyen bir model) aktif sayilir;
        router onu yalnizca ipucu olarak tasir, pasiflestiremez."""
        info = self.get(model_id)
        return info.active if info else True

    def chain_for(self, task_type: str, difficulty: str) -> tuple[str, list[str]]:
        name = (self.routes.get(task_type) or {}).get(difficulty) or self.default_chain
        return name, list(self.chains[name])

    def allowed(self, model_id: str, *, hint: str | None, task_type: str, explicit: bool = False) -> bool:
        """Ucret politikasi: ucretli model yalnizca ipucu ucretliyse, gorev tipi izinliyse
        ya da kullanici acikca istediyse secilebilir."""
        info = self.get(model_id)
        if info is None or not info.paid:
            return True
        hint_info = self.get(hint)
        if hint_info is not None and hint_info.paid:
            return True
        if task_type in self.paid_task_types:
            return True
        return bool(explicit and self.paid_explicit_ok)

    def fallback_for(self, model_id: str) -> str | None:
        """Pasif bir modelin yerine gecebilecek ilk AKTIF ve ucretsiz model: once ayni
        modeli iceren zincirlerdeki komsular, sonra varsayilan zincir."""
        candidates: list[str] = []
        for chain in self.chains.values():
            if model_id in chain:
                candidates += [m for m in chain if m != model_id]
        candidates += self.chains[self.default_chain]
        for cand in dict.fromkeys(candidates):
            info = self.get(cand)
            if info and info.active and info.routable and not info.paid:
                return cand
        return None

    # ------------------------------------------------------------------ erisilebilirlik
    def mark(self, model_id: str, *, active: bool, status: str, reason: str = "") -> None:
        info = self.get(model_id)
        if info is None:
            return
        info.active, info.status, info.reason = active, status, reason

    async def probe(self, *, gemini_key: str = "", openrouter_key: str = "", anthropic_key: str = "",
                    anthropic_workspace: str = "", ollama_url: str = "http://127.0.0.1:11434",
                    timeout: float = 6.0) -> dict[str, list[str]]:
        """Saglayici model listelerine bakarak her modeli aktif/pasif isaretler.

        Ag hatasi (liste alinamadi) modeli pasiflestirmez: 'dogrulanamadi' + WARNING.
        Anahtar yoksa ya da liste alindigi halde model listede yoksa PASIF.
        """
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as http:
            listings: dict[str, set[str] | Exception | None] = {}

            async def fetch(provider: str) -> None:
                try:
                    if provider == "openrouter":
                        resp = await http.get("https://openrouter.ai/api/v1/models")
                        resp.raise_for_status()
                        listings[provider] = {m["id"] for m in resp.json().get("data", [])} | {"openrouter/free"}
                    elif provider == "gemini":
                        if not gemini_key:
                            listings[provider] = None
                            return
                        resp = await http.get(
                            "https://generativelanguage.googleapis.com/v1beta/models",
                            params={"key": gemini_key, "pageSize": 1000},
                        )
                        resp.raise_for_status()
                        listings[provider] = {
                            m["name"].removeprefix("models/") for m in resp.json().get("models", [])
                        }
                    elif provider == "claude":
                        if not anthropic_key:
                            listings[provider] = None
                            return
                        headers = {"x-api-key": anthropic_key, "anthropic-version": "2023-06-01"}
                        if anthropic_workspace:
                            headers["anthropic-workspace-id"] = anthropic_workspace
                        resp = await http.get("https://api.anthropic.com/v1/models", headers=headers)
                        if resp.status_code in (400, 401, 403):   # ag hatasi degil: kesin yetki sorunu
                            try:
                                msg = resp.json().get("error", {}).get("message", "")
                            except ValueError:
                                msg = resp.text
                            listings[provider] = PermissionError(f"HTTP {resp.status_code}: {msg[:160]}")
                            return
                        resp.raise_for_status()
                        # Anahtar gecerli: model kimlikleri takma ad olabildigi icin liste
                        # birebir karsilastirilmaz (yanlis pasiflestirme olmasin).
                        listings[provider] = {"*"}
                    elif provider == "ollama":
                        resp = await http.get(f"{ollama_url.rstrip('/')}/api/tags")
                        resp.raise_for_status()
                        listings[provider] = {m["name"] for m in resp.json().get("models", [])}
                except Exception as exc:  # noqa: BLE001 - durum raporlanir
                    listings[provider] = exc

            import asyncio

            providers = sorted({m.provider for m in self.models.values()})
            await asyncio.gather(*(fetch(p) for p in providers))

        keys = {"openrouter": openrouter_key, "gemini": gemini_key, "claude": anthropic_key, "ollama": "yerel"}
        report: dict[str, list[str]] = {"erisilebilir": [], "pasif": [], "dogrulanamadi": []}
        for info in self.models.values():
            listing = listings.get(info.provider)
            if not keys.get(info.provider):
                self.mark(info.id, active=False, status="pasif", reason=f"{info.provider} anahtari yok")
            elif listing is None:
                self.mark(info.id, active=False, status="pasif", reason=f"{info.provider} anahtari yok")
            elif isinstance(listing, PermissionError):
                self.mark(info.id, active=False, status="pasif",
                          reason=f"{info.provider} anahtari reddedildi ({listing})")
            elif isinstance(listing, Exception):
                if info.provider == "ollama":
                    self.mark(info.id, active=False, status="pasif",
                              reason=f"Ollama calismiyor ({type(listing).__name__})")
                else:
                    self.mark(info.id, active=True, status="dogrulanamadi",
                              reason=f"model listesi alinamadi: {str(listing)[:120]}")
            elif "*" in listing or info.id in listing:
                self.mark(info.id, active=True, status="erisilebilir")
            else:
                self.mark(info.id, active=False, status="pasif",
                          reason=f"{info.provider} model listesinde yok (kaldirilmis olabilir)")
            report[self.models[info.id].status].append(info.id)

        for info in self.models.values():
            if info.status == "pasif":
                logger.warning(f"[router] PASIF model: {info.id} - {info.reason}")
            elif info.status == "dogrulanamadi":
                logger.warning(f"[router] Dogrulanamadi (aktif sayiliyor): {info.id} - {info.reason}")
        logger.success(
            f"[router] Model denetimi: {len(report['erisilebilir'])} erisilebilir, "
            f"{len(report['pasif'])} pasif, {len(report['dogrulanamadi'])} dogrulanamadi"
        )
        return report
