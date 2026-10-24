"""Proaktif CYRAEN - hatirlatici + rutin zamanlayicisi.

Durum dosya-tabanlidir (data/reminders.json, data/routines.json). Hem bu dongu hem
araclar (tools/scheduler_tools.py) ayni dosyalari okur/yazar - singleton gerekmez.

Vade gelince:
  - hatirlatici -> bridge/outbox.txt (CYRAEN sesli soyler) + Notifier
  - rutin(prompt) -> bridge/outbox.txt
  - rutin(agent_task) -> bridge/inbox.txt
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

_WEEKDAYS = {
    "pazartesi": 0, "sali": 1, "salı": 1, "carsamba": 2, "çarşamba": 2, "carşamba": 2,
    "persembe": 3, "perşembe": 3, "cuma": 4, "cumartesi": 5, "pazar": 6,
}


def _now() -> datetime:
    return datetime.now().astimezone()


_TR_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")

# gun dilimi -> saat duzeltmesi ("aksam 7" -> 19, "gece 2" -> 02, "oglen 1" -> 13)
_DAYPARTS: list[tuple[str, str]] = [
    ("ogleden sonra", "pm"), ("ikindi", "pm"), ("aksam", "pm"),
    ("gece", "night"), ("sabah", "am"), ("oglen", "noon"), ("ogle", "noon"),
]
_HOUR_SUFFIX = r"['’]?\s*(?:te|ta|de|da)\b"


def _apply_daypart(hour: int, part: str) -> int:
    if part == "pm":
        return hour + 12 if hour < 12 else hour
    if part == "noon":
        return hour + 12 if 1 <= hour <= 6 else hour
    if part == "night":
        if hour == 12:
            return 0
        return hour + 12 if 6 <= hour <= 11 else hour
    return 0 if (part == "am" and hour == 12) else hour


def parse_when(text: str, base: datetime | None = None) -> datetime | None:
    """Turkce dogal dil -> datetime. Cozemezse None.

    Ornekler: '20 dakika sonra', '17:30', 'saat 3' (13:00'te soylenirse 15:00 - bugunun en
    yakin gelecek ani), "3'te", 'aksam 7' (19:00), 'sabah 7', 'ogleden sonra 3',
    'yarin saat 9', 'cuma 15:00'.

    Belirsiz saat (gun dilimi yok, 1-12 arasi, '09:00' gibi sifirla yazilmamis):
    bugun icin h ve h+12'den gelecekteki en yakini; yarin/gun adi icin 1-6 arasi
    ogleden sonra sayilir (gece 3'te gorev kurmak yerine 15:00 daha olasi).
    """
    t = " ".join((text or "").strip().lower().split())
    ta = t.translate(_TR_ASCII)
    base = base or _now()

    m = re.search(r"(\d+)\s*(saniye|sn|dakika|dk|saat|gun|hafta)\s*sonra", ta)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit in ("saniye", "sn"):
            return base + timedelta(seconds=n)
        if unit in ("dakika", "dk"):
            return base + timedelta(minutes=n)
        if unit == "saat":
            return base + timedelta(hours=n)
        if unit == "gun":
            return base + timedelta(days=n)
        if unit == "hafta":
            return base + timedelta(weeks=n)

    part = next((p for word, p in _DAYPARTS if word in ta), None)
    hour, minute, have_time, padded = 9, 0, False, False
    hm = re.search(r"(?:saat\s*)?(\d{1,2})[:\.](\d{2})", ta)
    if hm:
        hour, minute, have_time = int(hm.group(1)), int(hm.group(2)), True
        padded = len(hm.group(1)) == 2 and hm.group(1).startswith("0")
    else:
        oh = (re.search(r"\bsaat\s*(\d{1,2})\b", ta)
              or re.search(r"\b(?:ogleden sonra|ikindi|aksam|gece|sabah|oglen|ogle)\s*(\d{1,2})\b", ta)
              or re.search(r"\b(\d{1,2})" + _HOUR_SUFFIX, ta))
        if oh:
            hour, have_time = int(oh.group(1)), True
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if part and have_time:
        hour = _apply_daypart(hour, part)
    ambiguous = have_time and part is None and 1 <= hour <= 12 and not padded

    def at(day: datetime, h: int) -> datetime:
        return day.replace(hour=h % 24, minute=minute, second=0, microsecond=0)

    def future_day(day: datetime) -> datetime:
        h = hour + 12 if ambiguous and 1 <= hour <= 6 else hour
        return at(day, h)

    if "yarin" in ta:
        return future_day(base + timedelta(days=1))

    for name, wd in _WEEKDAYS.items():
        if name.translate(_TR_ASCII) in ta.split() or name in t.split():
            days = (wd - base.weekday()) % 7 or 7
            return future_day(base + timedelta(days=days))

    if "bugun" in ta or have_time:
        hours = [hour, hour + 12] if ambiguous and hour < 12 else [hour]
        for day in (base, base + timedelta(days=1)):
            for h in hours:
                cand = at(day, h)
                if cand > base:
                    return cand
    return None


class Scheduler:
    def __init__(
        self,
        data_dir: Path,
        outbox_path: Path,
        inbox_path: Path,
        tick: float = 15.0,
        notifier: Any = None,
        bus: Any = None,
        default_briefing: bool = True,
    ) -> None:
        self.reminders_file = Path(data_dir) / "reminders.json"
        self.routines_file = Path(data_dir) / "routines.json"
        self.outbox = Path(outbox_path)
        self.inbox = Path(inbox_path)
        self.tick = max(3.0, tick)
        self.notifier = notifier
        self.bus = bus
        self._stop = threading.Event()
        for f in (self.reminders_file, self.routines_file):
            f.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_default_routine(enabled=default_briefing)

    # ------------------------------------------------------------------ loop
    def run(self) -> None:
        logger.success(f"Zamanlayici aktif (tick {self.tick:.0f}s)")
        self._publish()
        while not self._stop.wait(self.tick):
            self.tick_once()

    def tick_once(self) -> None:
        """Tek kontrol turu (hatirlatici + rutin). SchedulerHandler bunu APScheduler isi
        olarak cagirir; `run()` ise eski thread'li kullanim icin ayni turu dongude yapar."""
        try:
            self._check_reminders()
            self._check_routines()
        except Exception:  # noqa: BLE001
            logger.exception("Zamanlayici tick hatasi")

    def request_shutdown(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ reminders
    def _check_reminders(self) -> None:
        items = _load(self.reminders_file)
        now = _now()
        changed = False
        for r in items:
            if r.get("done"):
                continue
            try:
                fire = datetime.fromisoformat(r["fire_at"])
            except Exception:  # noqa: BLE001
                r["done"] = True
                changed = True
                continue
            if fire <= now:
                text = r.get("text", "hatirlatma")
                if r.get("action") == "agent_task":
                    self._fire_task(r)
                else:
                    self._append(self.outbox, f"[HATIRLATICI] {text}")
                    self._notify("Hatirlatici", text, tags=["bell"])
                    logger.info(f"Hatirlatici tetiklendi: {text}")
                r["done"] = True
                changed = True
        if changed:
            items = [r for r in items if not (r.get("done") and _older_than(r, 3600))]
            _save(self.reminders_file, items)
            self._publish()

    def _fire_task(self, r: dict[str, Any]) -> None:
        """Zamanli gorev: isi orkestratore (bridge/inbox.txt) verir, CYRAEN'e haber verir.

        `source` "zamanli" ile baslar -> orkestrator onay beklemez (kullanici gorevi
        kurarken onaylamistir); "zamanli:not" ise sonucu notlara da kaydeder.
        """
        task = r.get("text", "")
        rec = {
            "id": f"zt{r.get('id', uuid.uuid4().hex[:8])}",
            "agent": r.get("agent") or "auto",
            "task": task,
            "source": "zamanli:not" if r.get("save_note") else "zamanli",
            "created_at": _now().isoformat(timespec="seconds"),
        }
        self._append(self.inbox, json.dumps(rec, ensure_ascii=False))
        self._append(self.outbox, f"[ZAMANLI GOREV] Basladi: {task}")
        logger.info(f"Zamanli gorev tetiklendi -> {rec['agent']}: {task}")

    # ------------------------------------------------------------------ routines
    def _check_routines(self) -> None:
        items = _load(self.routines_file)
        now = _now()
        changed = False
        for r in items:
            if not r.get("enabled", True):
                continue
            due_at = _routine_due(r, now)
            last = r.get("last_run", "")
            if due_at is None:
                continue
            if last and datetime.fromisoformat(last) >= due_at:
                continue
            action = r.get("action", "prompt")
            payload = r.get("payload", "")
            name = r.get("name", r.get("id", "rutin"))
            if action == "agent_task":
                rec = {"id": f"rt{int(time.time())}", "agent": "auto",
                       "task": payload, "source": f"rutin:{name}"}
                self._append(self.inbox, json.dumps(rec, ensure_ascii=False))
            else:
                self._append(self.outbox, f"[RUTIN:{name}] {payload}")
            r["last_run"] = now.isoformat(timespec="seconds")
            changed = True
            logger.info(f"Rutin tetiklendi: {name}")
        if changed:
            _save(self.routines_file, items)
            self._publish()

    def _ensure_default_routine(self, enabled: bool = True) -> None:
        """Varsayilan 09:00 'Gunluk Brifing' rutini. SchedulerHandler'in sabah ozeti
        aciksa `enabled=False` ile kapatilir (iki kez brifing olmasin)."""
        items = _load(self.routines_file)
        existing = next((r for r in items if r.get("id") == "daily_briefing"), None)
        if existing is not None:
            if bool(existing.get("enabled", True)) != enabled:
                existing["enabled"] = enabled
                _save(self.routines_file, items)
                logger.info(f"'Gunluk Brifing' rutini {'acildi' if enabled else 'kapatildi (sabah ozeti devraldi)'}")
            return
        items.append({
            "id": "daily_briefing", "name": "Gunluk Brifing", "enabled": enabled,
            "schedule": "her gun 09:00", "action": "agent_task",
            "payload": "Gunluk brifing: gelen kutusundaki okunmamis onemli mailleri ozetle, "
                       "bugunun hava durumunu ekle, bekleyen hatirlaticilar varsa hatirlat.",
            "last_run": "",
        })
        _save(self.routines_file, items)

    # ------------------------------------------------------------------ io
    def _append(self, path: Path, line: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as h:
                h.write(" ".join(line.split()).strip() + "\n")
        except OSError as exc:
            logger.error(f"zamanlayici yazamadi: {exc}")

    def _notify(self, title: str, message: str, tags: list[str] | None = None) -> None:
        if self.notifier is None:
            return
        try:
            import asyncio
            coro = self.notifier.notify(title, message, priority=4, tags=tags or [])
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(coro)
                    return
            except RuntimeError:
                pass
            asyncio.run(coro)
        except Exception:  # noqa: BLE001
            logger.debug("notifier cagrilamadi (zamanlayici)")

    def _publish(self) -> None:
        if self.bus is None:
            return
        try:
            rem = [
                {"text": r.get("text"), "fire_at": r.get("fire_at"),
                 "fire_at_h": _fmt(r.get("fire_at"))}
                for r in _load(self.reminders_file) if not r.get("done")
            ]
            self.bus.push("reminders", rem)
            self.bus.push("routines", [
                {"name": r.get("name"), "schedule": r.get("schedule"),
                 "enabled": r.get("enabled", True)}
                for r in _load(self.routines_file)
            ])
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------- module helpers

def _load(path: Path) -> list[dict[str, Any]]:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        pass
    return []


def _save(path: Path, items: list[dict[str, Any]]) -> None:
    try:
        path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        logger.error(f"kayit yazilamadi ({path.name}): {exc}")


def _fmt(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m %H:%M")
    except Exception:  # noqa: BLE001
        return iso or ""


def _older_than(rec: dict, seconds: float) -> bool:
    try:
        return (_now() - datetime.fromisoformat(rec["fire_at"])).total_seconds() > seconds
    except Exception:  # noqa: BLE001
        return True


def _routine_due(r: dict, now: datetime) -> datetime | None:
    """Rutinin BUGUN icin tetiklenmesi gereken an (gecmisse) veya None."""
    sched = (r.get("schedule") or "").strip().lower()
    m = re.search(r"(\d{1,2})[:\.](\d{2})", sched)
    hh, mm = (int(m.group(1)), int(m.group(2))) if m else (9, 0)
    if "her saat" in sched:
        cand = now.replace(minute=mm, second=0, microsecond=0)
        return cand if cand <= now else None
    if "her gun" in sched or "her gün" in sched or "gunluk" in sched or m:
        cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return cand if cand <= now else None
    for name, wd in _WEEKDAYS.items():
        if name in sched and now.weekday() == wd:
            cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            return cand if cand <= now else None
    return None


# --------------------------------------------------------------- tool-facing API

def add_reminder_record(data_dir: Path, text: str, when: str) -> dict[str, Any]:
    fire = parse_when(when)
    if fire is None:
        return {"error": f"Zamani anlayamadim: '{when}'. Ornek: '20 dakika sonra', 'yarin 09:00', '17:30'."}
    path = Path(data_dir) / "reminders.json"
    items = _load(path)
    rec = {"id": uuid.uuid4().hex[:8], "text": text.strip(),
           "fire_at": fire.isoformat(timespec="seconds"), "done": False}
    items.append(rec)
    _save(path, items)
    return {"status": "kuruldu", "text": rec["text"], "ne_zaman": fire.strftime("%d.%m.%Y %H:%M")}


def add_task_record(
    data_dir: Path, task: str, when: str, *, agent: str = "auto", save_note: bool = True
) -> dict[str, Any]:
    """Tek seferlik zamanli ajan gorevi (hatirlaticilarla ayni dosyada, action=agent_task)."""
    fire = parse_when(when)
    if fire is None:
        return {"error": f"Zamani anlayamadim: '{when}'. Ornek: '15:00', 'saat 3', 'aksam 7', 'yarin 09:00'."}
    path = Path(data_dir) / "reminders.json"
    items = _load(path)
    rec = {"id": uuid.uuid4().hex[:8], "text": task.strip(), "action": "agent_task",
           "agent": (agent or "auto").strip() or "auto", "save_note": bool(save_note),
           "fire_at": fire.isoformat(timespec="seconds"), "done": False}
    items.append(rec)
    _save(path, items)
    return {"status": "zamanli gorev kuruldu", "task": rec["text"], "agent": rec["agent"],
            "ne_zaman": fire.strftime("%d.%m.%Y %H:%M"), "not_alinacak": rec["save_note"]}
