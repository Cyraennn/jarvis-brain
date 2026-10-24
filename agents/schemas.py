"""Cok-ajanli sistem veri modelleri (kisisel asistan departman hiyerarsisi)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TaskStatus = Literal[
    "queued",
    "routing",
    "running",
    "tool",
    "awaiting_approval",
    "done",
    "failed",
    "cancelled",
    "blocked",
]


class Department(str, Enum):
    OKUL = "okul"
    ILETISIM = "iletisim"
    SISTEM = "sistem"
    TELEFON = "telefon"
    BILGI = "bilgi"
    GUNLUK = "gunluk"
    GELISTIRME = "gelistirme"
    YONETIM = "yonetim"


DEPARTMENT_TITLES: dict[Department, str] = {
    Department.OKUL: "Okul",
    Department.ILETISIM: "İletişim",
    Department.SISTEM: "Sistem",
    Department.TELEFON: "Telefon",
    Department.BILGI: "Bilgi",
    Department.GUNLUK: "Günlük & Medya",
    Department.GELISTIRME: "Geliştirme",
    Department.YONETIM: "Yönetim",
}

_TR_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def parse_department(value: object) -> Department | None:
    """'geliştirme' / 'Yönetim' gibi yazimlari enum'a cevirir; bilinmiyorsa None."""
    if value is None or isinstance(value, Department):
        return value
    key = str(value).strip().translate(_TR_ASCII).lower()
    for d in Department:
        if key in (d.value, d.name.lower()):
            return d
    return None


class Autonomy(str, Enum):
    HUMAN_LED = "human_led"           # yalnizca insan baslatir
    HUMAN_ASSISTED = "human_assisted"  # CYRAEN onerir, insan onaylar
    FULLY_AUTONOMOUS = "fully_autonomous"  # CYRAEN dogrudan calistirir


AUTONOMY_BADGE: dict[Autonomy, str] = {
    Autonomy.HUMAN_LED: "İnsan Odaklı",
    Autonomy.HUMAN_ASSISTED: "İnsan Onaylı",
    Autonomy.FULLY_AUTONOMOUS: "Tam Otonom",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class AgentSpec(BaseModel):
    """Bir uzman ajanin / yetenegin tanimi."""

    name: str                       # kod adi (routing anahtari, benzersiz)
    title: str                      # insan-okur etiket
    description: str                # ne zaman kullanilir (conductor bunu okur)
    department: Department | None = None
    autonomy: Autonomy = Autonomy.HUMAN_ASSISTED
    sop: str = ""                   # Standart Calisma Proseduru (detay panelinde)
    skills: list[str] = Field(default_factory=list)   # indirilebilir yetenek dosyalari
    skill: str | None = None        # deterministik skill callable adi (varsa once o calisir)

    system_prompt: str = ""
    capabilities: list[str] = Field(default_factory=list)
    grounded_search: bool = False
    # "claude-*" -> Claude, "saglayici/model" bicimi -> OpenRouter, digerleri -> Gemini
    model: str | None = None
    fallback_model: str | None = None
    temperature: float = 0.5        # Claude yolunda kullanilmaz (yerine `effort`)
    effort: str | None = None       # Claude: low | medium | high | xhigh | max
    max_steps: int | None = None

    @field_validator("department", mode="before")
    @classmethod
    def _normalize_department(cls, value: object) -> Department | None:
        return parse_department(value)


class DepartmentSpec(BaseModel):
    key: Department
    title: str
    description: str
    agents: list[AgentSpec]


class RoutingDecision(BaseModel):
    department: Department | None = None
    agent: str = ""
    reason: str = ""
    confidence: float = 0.0


class TaskRequest(BaseModel):
    id: str = Field(default_factory=_new_id)
    agent: str = "auto"
    task: str
    source: str = "cyraen"
    context: str = ""
    created_at: str = Field(default_factory=_now)


class TaskUpdate(BaseModel):
    id: str
    agent: str
    status: TaskStatus
    department: str = ""
    autonomy: str = ""
    detail: str = ""
    steps: int = 0
    result: str | None = None
    updated_at: str = Field(default_factory=_now)


class AgentResult(BaseModel):
    ok: bool
    text: str
    steps: int = 0
    tool_calls: list[str] = Field(default_factory=list)
    error: str | None = None
    artifact: dict | None = None   # skill ciktisi (rapor vb.)
    model: str | None = None       # son cagrida gercekten kullanilan model
    fallback: bool = False         # herhangi bir adimda yedek modele gecildi mi
    primary_model: str | None = None
