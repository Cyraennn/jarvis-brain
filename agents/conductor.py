"""JARVIS Conductor - ust duzey komuta/orkestrasyon ajani.

Karmasik bir gorevi analiz eder, 6 kisisel asistan departmanindan (okul, iletisim,
sistem, telefon, bilgi, gunluk) birine ve o departmandaki bir alt ajana delege eder. (Sesli beyin ile ayni Gemini altyapisi; Ollama'ya `backends`
soyutlamasi eklenirse degistirilebilir.)
"""

from __future__ import annotations

import json
import re
from typing import Any

from google import genai
from google.genai import types
from loguru import logger

from agents.departments import DEPARTMENTS, all_agents, department_catalog
from agents.genai_util import generate_with_retry
from agents.schemas import AgentSpec, Department, RoutingDecision, parse_department

_SYSTEM = (
    "Sen JARVIS'sin - Sezai'nin (DEU BOTE ogrencisi) kisisel asistaninin orkestratoru. "
    "Verilen gorevi analiz eder ve "
    "asagidaki departman/alt-ajan kataloguna gore EN UYGUN tek alt ajana delege "
    "edersin. Yalnizca su JSON'u dondur:\n"
    '{\"department\": \"<departman_kodu>\", \"agent\": \"<ajan_kod_adi>\", '
    '\"reason\": \"<tek cumle>\", \"confidence\": <0-1>}'
)


class Conductor:
    def __init__(
        self,
        client: genai.Client,
        models: list[str],
        *,
        agents: dict[str, AgentSpec] | None = None,
        openrouter: Any | None = None,
        openrouter_models: list[str] | None = None,
    ) -> None:
        self.client = client
        self.models = models
        self._agents = agents if agents is not None else all_agents()
        self._catalog = department_catalog(agents)
        # agents.json "orchestrator" blogu: once OpenRouter, sonra Gemini zinciri
        self.openrouter = openrouter
        self.openrouter_models = [m for m in (openrouter_models or []) if m]

    async def _route_openrouter(self, prompt: str, info: dict) -> dict | None:
        if not self.openrouter_models or not getattr(self.openrouter, "available", False):
            return None
        primary, *fallbacks = self.openrouter_models
        try:
            text = await self.openrouter.generate_response(
                prompt, model=primary, fallback_models=fallbacks, info=info, temperature=0.0,
            )
            return _parse_json(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Conductor OpenRouter yonlendirmesi basarisiz, Gemini'ye geciliyor: {exc!r}")
            info.clear()
            return None

    async def route(self, task: str, context: str = "") -> RoutingDecision:
        prompt = (
            f"{_SYSTEM}\n\n=== KATALOG ==={self._catalog}\n\n"
            f"=== GOREV ===\n{task}\n"
            + (f"\n=== BAGLAM ===\n{context}\n" if context else "")
        )
        try:
            info: dict = {}
            data = await self._route_openrouter(prompt, info)
            if data is None:
                gemini_info: dict = {}
                resp = await generate_with_retry(
                    self.client,
                    model=self.models,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                    ),
                    attempts=2,
                    info=gemini_info,
                )
                info["model"] = gemini_info.get("model")
                # OpenRouter tanimliyken Gemini'ye dusmek de bir yedek gecisidir
                info["fallback"] = bool(self.openrouter_models) or bool(gemini_info.get("fallback"))
                data = json.loads((getattr(resp, "text", None) or "{}").strip())
            dept = self._as_department(data.get("department"))
            agent = str(data.get("agent", "")).strip()
            if agent not in self._agents:
                agent = self._first_agent(dept)
            reason = str(data.get("reason", ""))[:200]
            if info.get("fallback"):
                reason = f"[YEDEK MODEL {info.get('model')}] {reason}"
            return RoutingDecision(
                department=dept or self._agents[agent].department,
                agent=agent,
                reason=reason,
                confidence=float(data.get("confidence", 0.5) or 0.5),
            )
        except Exception as exc:  # noqa: BLE001
            # Model hic yanit vermedi: anahtar kelime yonlendirmesine dusulur. Bu da bir
            # yedek yoldur -> ERROR seviyesinde ve kancalarla ACIKCA bildirilir.
            logger.bind(event="routing_fallback").error(
                f"Conductor modeli yanit vermedi, ANAHTAR KELIME yonlendirmesine dusuluyor: {exc!r}"
            )
            from agents.genai_util import FALLBACK_HOOKS

            for hook in list(FALLBACK_HOOKS):
                try:
                    hook({"from": "conductor", "to": "anahtar-kelime", "reason": str(exc)[:200]})
                except Exception:  # noqa: BLE001
                    logger.exception("fallback kancasi hata verdi")
            decision = self._fallback(task)
            decision.reason = f"[YEDEK YONLENDIRME - model yok] {decision.reason}"
            return decision

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _as_department(value: object) -> Department | None:
        return parse_department(value) if value else None

    def _first_agent(self, dept: Department | None) -> str:
        if dept and dept in DEPARTMENTS and DEPARTMENTS[dept].agents:
            return DEPARTMENTS[dept].agents[0].name
        for name, spec in self._agents.items():
            if dept and spec.department == dept:
                return name
        return next(iter(self._agents))

    def _fallback(self, task: str) -> RoutingDecision:
        low = task.lower()
        table = [
            (("markdown", ".md", "dokuman"), "markdown_denetcisi"),
            (("sinav", "sınav", "calisma plan", "çalışma plan"), "sinav_kocu"),
            (("odev", "ödev"), "odev_takipcisi"),
            (("ders program", "bugun ders", "bugün ders", "yarin ders", "yarın ders"), "ders_programi"),
            (("gano", "ortalama"), "gano_danismani"),
            (("brifing", "gunun ozeti", "günün özeti"), "gunluk_brifing"),
            (("hatirlat", "hatırlat", "rutin", "alarm"), "hatirlatici"),
            (("otobus", "otobüs", "eshot", "durak", "izmirim", "rota", "nasil giderim", "nasıl giderim"), "ulasim"),
            (("siteye gir", "sitesine gir", "sitede ", "formu doldur", "kargo", "takip numara",
              "tarayicida", "tarayıcıda"), "web_operatoru"),
            (("mcp", "github", "notion"), "entegrasyon_uzmani"),
            (("hava",), "hava_durumu"),
            (("harcama", "masraf"), "harcama_defteri"),
            (("telefon", "android", "adb"), "telefon_operatoru"),
            (("telegram",), "sekreter"),
            (("mail", "e-posta", "eposta", "email"), "eposta_triyaj"),
            (("kod", "code", "refactor", "bug"), "kod_denetcisi"),
            (("temizlik", "yer ac", "yer aç", "disk dol", "cop kutusu", "çöp kutusu", "onbellek", "önbellek"),
             "bakim_teknisyeni"),
            (("sistem", "cpu", "disk", "ram", "saglik", "sağlık"), "sistem_sagligi"),
            (("muzik", "müzik", "sarki", "şarkı", "spotify"), "muzik_dj"),
            (("not al", "not et", "kaydet"), "not_katibi"),
            (("ozetle", "özetle", "belge"), "belge_ozetleyici"),
        ]
        for keys, agent in table:
            if any(k in low for k in keys) and agent in self._agents:
                spec = self._agents[agent]
                return RoutingDecision(department=spec.department, agent=agent,
                                       reason="anahtar kelime eslesmesi", confidence=0.4)
        default = "arastirmaci" if "arastirmaci" in self._agents else next(iter(self._agents))
        return RoutingDecision(department=self._agents[default].department, agent=default,
                               reason="varsayilan", confidence=0.2)


def _parse_json(text: str) -> dict:
    """Serbest metin yanittan ilk JSON nesnesini ayiklar (```json bloklari dahil)."""
    text = (text or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("yonlendirme yaniti JSON nesnesi degil")
    return data
