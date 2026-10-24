"""Hatirlatici + rutin araclari (dosya-tabanli; calisan Scheduler ayni dosyalari okur)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from config.settings import get_settings
from core.scheduler import _load, _save, add_reminder_record, add_task_record, parse_when


def _dir() -> Path:
    return get_settings().data_dir


def set_reminder(text: str, when: str) -> dict[str, Any]:
    """Bir hatirlatici kurar. `when` dogal dil: '20 dakika sonra', 'yarin 09:00', '17:30', 'cuma 15:00'."""
    if not (text or "").strip():
        return {"error": "Hatirlatilacak metin bos."}
    return add_reminder_record(_dir(), text, when)


def schedule_task(task: str, when: str, agent: str = "auto", save_note: bool = True) -> dict[str, Any]:
    """Bir isi ileri bir zamanda ajana yaptirir (orn. 'saat 3'te sunu analiz et').
    Vakti gelince gorev ajana verilir; save_note=True ise sonuc notlara (Obsidian) kaydedilir
    ve CYRAEN sonucu sesli bildirir. `when`: '15:00', 'saat 3', 'aksam 7', 'yarin 09:00'."""
    if not (task or "").strip():
        return {"error": "Yapilacak is (task) bos."}
    return add_task_record(_dir(), task, when, agent=agent, save_note=save_note)


def list_reminders() -> dict[str, Any]:
    """Bekleyen hatirlatici ve zamanli gorevleri listeler."""
    items = [r for r in _load(_dir() / "reminders.json") if not r.get("done")]
    items.sort(key=lambda r: r.get("fire_at", ""))
    return {"count": len(items), "reminders": [
        {"id": r["id"], "text": r["text"], "fire_at": r["fire_at"],
         "tur": "zamanli gorev" if r.get("action") == "agent_task" else "hatirlatici"}
        for r in items
    ]}


def cancel_reminder(id_or_text: str) -> dict[str, Any]:
    """Bir hatirlaticiyi iptal eder (id veya metin parcasi ile)."""
    path = _dir() / "reminders.json"
    items = _load(path)
    key = (id_or_text or "").strip().lower()
    removed = [r for r in items if r["id"] == key or key in r.get("text", "").lower()]
    if not removed:
        return {"error": f"Eslesime bulunamadi: {id_or_text}"}
    kept = [r for r in items if r not in removed]
    _save(path, kept)
    return {"status": "iptal edildi", "silinen": [r["text"] for r in removed]}


def add_routine(name: str, schedule: str, instruction: str, as_agent_task: bool = True) -> dict[str, Any]:
    """Zamanlanmis rutin ekler. `schedule`: 'her gun 09:00', 'her saat', 'pazartesi 10:00'."""
    if not name.strip() or not instruction.strip():
        return {"error": "name ve instruction zorunlu."}
    if parse_when(schedule) is None and not any(
        k in schedule.lower() for k in ("her gun", "her gün", "her saat", "gunluk")
    ) and not any(k in schedule.lower() for k in
                  ("pazartesi", "sali", "salı", "carsamba", "çarşamba", "persembe",
                   "perşembe", "cuma", "cumartesi", "pazar")):
        return {"error": f"Zamanlamayi anlayamadim: '{schedule}'"}
    path = _dir() / "routines.json"
    items = _load(path)
    rec = {"id": uuid.uuid4().hex[:8], "name": name.strip(), "enabled": True,
           "schedule": schedule.strip(),
           "action": "agent_task" if as_agent_task else "prompt",
           "payload": instruction.strip(), "last_run": ""}
    items.append(rec)
    _save(path, items)
    return {"status": "eklendi", "name": rec["name"], "schedule": rec["schedule"]}


def list_routines() -> dict[str, Any]:
    """Tanimli rutinleri listeler."""
    items = _load(_dir() / "routines.json")
    return {"count": len(items), "routines": [
        {"id": r["id"], "name": r["name"], "schedule": r["schedule"],
         "enabled": r.get("enabled", True), "action": r.get("action")}
        for r in items
    ]}


def remove_routine(id_or_name: str) -> dict[str, Any]:
    """Bir rutini siler (id veya ad ile)."""
    path = _dir() / "routines.json"
    items = _load(path)
    key = (id_or_name or "").strip().lower()
    removed = [r for r in items if r["id"] == key or key in r.get("name", "").lower()]
    if not removed:
        return {"error": f"Eslesme bulunamadi: {id_or_name}"}
    _save(path, [r for r in items if r not in removed])
    return {"status": "silindi", "silinen": [r["name"] for r in removed]}
