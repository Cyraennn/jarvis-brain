"""okul (BOTE Ders Merkezi) kopru araclari.

okul web uygulamasi tam localStorage durumunu web konsoluna gonderir
(`/api/okul/push` -> `data/okul_state.json`). Buradaki araclar o durumu okur;
`okul_add_*` araclari `data/okul_outbox.json`'a bir islem ekler, okul bir sonraki
`/api/okul/pull` cagrisinda bunlari kendi verisine katar.

Saf dosya G/C - senkron; `ToolRunner` bunlari `asyncio.to_thread` ile calistirir.
okul hic baglanmadiysa araclar kullanici dostu bir hata dondurur (sistem cokmez).
"""

from __future__ import annotations

import contextlib
import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import get_settings

# okul schedule.js: 0=Pazartesi ... 4=Cuma  (Python date.weekday() ile ayni)
_DAYS_TR = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi", "Pazar"]
_DAY_ALIASES = {
    "pazartesi": 0, "sali": 1, "salı": 1, "carsamba": 2, "çarşamba": 2, "carşamba": 2,
    "persembe": 3, "perşembe": 3, "cuma": 4, "cumartesi": 5, "pazar": 6,
    "bugun": None, "bugün": None, "yarin": "TOMORROW", "yarın": "TOMORROW",
}
_GRADES = {
    "AA": 4.0, "BA": 3.5, "BB": 3.0, "CB": 2.5, "CC": 2.0,
    "DC": 1.5, "DD": 1.0, "FD": 0.5, "FF": 0.0, "DZ": 0.0,
}


# --------------------------------------------------------------------- durum G/C

def _state_path() -> Path:
    return Path(get_settings().okul_state_path)


def _outbox_path() -> Path:
    return Path(get_settings().okul_outbox_path)


def _enabled() -> bool:
    return bool(getattr(get_settings(), "okul_enabled", True))


def _load() -> dict[str, Any] | None:
    """okul'un son gonderdigi `data` sozlugu; hic baglanmadiysa None."""
    if not _enabled():
        return None
    path = _state_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw.get("data") if isinstance(raw, dict) else None
    except (OSError, ValueError) as exc:
        logger.warning(f"okul durumu okunamadi: {exc}")
        return None


def _not_connected() -> dict[str, Any]:
    return {
        "error": (
            "okul (BOTE Ders Merkezi) henuz baglanmadi. okul uygulamasini ac, "
            "Ayarlar > CYRAEN'e baglan bolumunden bu PC'nin adresini ve tokenini gir."
        )
    }


def _append_op(op: str, payload: dict[str, Any]) -> dict[str, Any]:
    """okul'a iletilecek bir islemi outbox kuyruguna ekler."""
    path = _outbox_path()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "op": op,
        "payload": payload,
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ops: list[Any] = []
        if path.is_file():
            with contextlib.suppress(ValueError):
                ops = json.loads(path.read_text(encoding="utf-8")) or []
        ops.append(entry)
        path.write_text(json.dumps(ops, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning(f"okul outbox yazilamadi: {exc}")
        return {"error": f"Kuyruga eklenemedi: {exc}"}
    connected = _state_path().is_file()
    note = (
        "okul uygulamasi acik/odakta oldugunda birkac saniye icinde islenir."
        if connected else
        "DIKKAT: okul henuz CYRAEN'e baglanmadi - islem kuyrukta bekliyor. "
        "okul'da Ayarlar > CYRAEN baglantisi kurulunca otomatik uygulanir."
    )
    return {"status": "kuyruga alindi", "id": entry["id"], "okul_bagli": connected, "note": note}


# --------------------------------------------------------------------- yardimcilar

def _today() -> date:
    return datetime.now().astimezone().date()


def _parse_iso(s: Any) -> date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _days_until(iso: Any) -> int | None:
    d = _parse_iso(iso)
    return (d - _today()).days if d else None


def _courses(data: dict[str, Any]) -> list[str]:
    names: set[str] = set()
    for key, field in (
        ("schedule", "name"), ("grades_courses", "name"), ("exams", "course"),
        ("tasks", "course"), ("attendance", "course"),
    ):
        for row in data.get(key, []) or []:
            v = (row or {}).get(field)
            if v:
                names.add(str(v))
    return sorted(names)


def _upcoming_exams(data: dict[str, Any], days: int) -> list[dict[str, Any]]:
    out = []
    for e in data.get("exams", []) or []:
        if not e or e.get("done"):
            continue
        du = _days_until(e.get("date"))
        if du is None or du < 0 or du > days:
            continue
        out.append({
            "ders": e.get("course"), "tur": e.get("type") or "Sinav",
            "tarih": e.get("date"), "saat": e.get("time") or "",
            "yer": e.get("location") or "", "kalan_gun": du,
            "konular": [t for t in (e.get("topics") or "").splitlines() if t.strip()],
        })
    return sorted(out, key=lambda x: x["kalan_gun"])


def _open_tasks(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for t in data.get("tasks", []) or []:
        if not t or t.get("status") == "Tamamlandi" or t.get("status") == "Tamamlandı":
            continue
        du = _days_until(t.get("due"))
        out.append({
            "baslik": t.get("title"), "ders": t.get("course") or "",
            "teslim": t.get("due") or "", "kalan_gun": du,
            "oncelik": t.get("priority") or "Orta", "durum": t.get("status") or "Yapilacak",
        })
    return sorted(out, key=lambda x: (x["kalan_gun"] is None, x["kalan_gun"]))


def _schedule_for(data: dict[str, Any], day_idx: int) -> list[dict[str, Any]]:
    rows = []
    for s in data.get("schedule", []) or []:
        if not s or int(s.get("day", -1)) != day_idx:
            continue
        rows.append({
            "ders": s.get("name"), "baslangic": f"{int(s.get('start', 0)):02d}:00",
            "bitis": f"{int(s.get('end', 0)):02d}:00",
            "derslik": s.get("room") or "", "hoca": s.get("instructor") or "",
        })
    return sorted(rows, key=lambda r: r["baslangic"])


# --------------------------------------------------------------------- araclar (okuma)

def okul_status() -> dict[str, Any]:
    """Ozet: yaklasan sinavlar, teslim edilecek odevler ve bugunku ders programi."""
    data = _load()
    if data is None:
        return _not_connected()
    today = _today()
    exams = _upcoming_exams(data, 14)
    tasks = _open_tasks(data)
    overdue = [t for t in tasks if t["kalan_gun"] is not None and t["kalan_gun"] < 0]
    soon = [t for t in tasks if t["kalan_gun"] is not None and 0 <= t["kalan_gun"] <= 7]
    return {
        "tarih": today.isoformat(),
        "bugun": _DAYS_TR[today.weekday()],
        "yaklasan_sinavlar": exams[:6],
        "geciken_odevler": overdue,
        "yakin_odevler": soon,
        "acik_odev_sayisi": len(tasks),
        "bugunku_program": _schedule_for(data, today.weekday()),
    }


def okul_next_exams(days: int = 14) -> dict[str, Any]:
    """Onumuzdeki `days` gun icindeki sinavlari listeler (varsayilan 14)."""
    data = _load()
    if data is None:
        return _not_connected()
    try:
        days = max(1, min(120, int(days)))
    except (TypeError, ValueError):
        days = 14
    ex = _upcoming_exams(data, days)
    return {"gun": days, "sayi": len(ex), "sinavlar": ex}


def okul_today_tasks() -> dict[str, Any]:
    """Bugun veya daha once teslim edilmesi gereken, tamamlanmamis odevler."""
    data = _load()
    if data is None:
        return _not_connected()
    tasks = [t for t in _open_tasks(data) if t["kalan_gun"] is not None and t["kalan_gun"] <= 0]
    return {"sayi": len(tasks), "odevler": tasks}


def okul_schedule(day: str | None = None) -> dict[str, Any]:
    """Bir gunun ders programi. `day`: 'pazartesi'..'cuma', 'bugun', 'yarin' ya da bos (bugun)."""
    data = _load()
    if data is None:
        return _not_connected()
    idx = _today().weekday()
    if day:
        key = str(day).strip().lower()
        if key in _DAY_ALIASES:
            val = _DAY_ALIASES[key]
            if val == "TOMORROW":
                idx = (_today() + timedelta(days=1)).weekday()
            elif val is not None:
                idx = val
        elif key.isdigit():
            idx = max(0, min(6, int(key)))
    return {"gun": _DAYS_TR[idx], "dersler": _schedule_for(data, idx)}


def okul_gpa() -> dict[str, Any]:
    """Girilen harf notlarindan GANO (genel) ve yariyil bazli ortalamalari hesaplar."""
    data = _load()
    if data is None:
        return _not_connected()
    rows = data.get("grades_courses", []) or []
    def _calc(items: list[dict[str, Any]]) -> dict[str, Any]:
        pts = cr = 0.0
        for c in items:
            g = _GRADES.get((c or {}).get("grade"))
            if g is None:
                continue
            k = float((c or {}).get("credit") or 0)
            pts += g * k
            cr += k
        return {"gano": round(pts / cr, 2) if cr else None, "kredi": cr}
    terms: dict[str, list[dict[str, Any]]] = {}
    for c in rows:
        terms.setdefault(str((c or {}).get("term") or "?"), []).append(c)
    return {
        "genel": _calc(rows),
        "yariyillar": {t: _calc(v) for t, v in sorted(terms.items())},
        "ders_sayisi": len(rows),
    }


def okul_search_notes(query: str) -> dict[str, Any]:
    """Not baslik/etiket/govdesinde metin arar; eslesenlerin ozetini dondurur."""
    data = _load()
    if data is None:
        return _not_connected()
    q = (query or "").strip().lower()
    if not q:
        return {"error": "arama metni bos"}
    hits = []
    for n in data.get("notes", []) or []:
        blob = " ".join(str((n or {}).get(k, "")) for k in ("title", "tags", "body")).lower()
        if q in blob:
            body = str((n or {}).get("body", ""))
            hits.append({
                "baslik": n.get("title") or "Basliksiz",
                "etiketler": n.get("tags") or "",
                "ozet": body[:400] + ("..." if len(body) > 400 else ""),
                "guncelleme": n.get("updated") or "",
            })
    return {"sorgu": q, "sayi": len(hits), "notlar": hits[:8]}


# --------------------------------------------------------------------- araclar (yazma)

def okul_add_task(
    title: str,
    course: str = "",
    due: str = "",
    priority: str = "Orta",
    notes: str = "",
) -> dict[str, Any]:
    """okul'a yeni bir odev/gorev ekler. `due` ISO tarih (YYYY-MM-DD)."""
    if not _enabled():
        return {"error": "okul koprusu kapali (CYRAEN_OKUL_ENABLED=false)."}
    title = (title or "").strip()
    if not title:
        return {"error": "'title' zorunlu"}
    d = _parse_iso(due) if due else None
    _prio = {"dusuk": "Düşük", "düşük": "Düşük", "low": "Düşük",
             "yuksek": "Yüksek", "yüksek": "Yüksek", "high": "Yüksek"}
    payload = {
        "title": title,
        "course": (course or "").strip(),
        "due": d.isoformat() if d else "",
        "priority": _prio.get((priority or "").strip().lower(), "Orta"),
        "status": "Yapılacak",
        "notes": (notes or "").strip(),
    }
    res = _append_op("add_task", payload)
    res["eklenen"] = {"baslik": title, "ders": payload["course"], "teslim": payload["due"] or "yok"}
    return res


def okul_add_exam(
    course: str,
    exam_date: str,
    exam_type: str = "Vize",
    topics: str = "",
    exam_time: str = "",
    location: str = "",
) -> dict[str, Any]:
    """okul'a yeni bir sinav ekler. `exam_date` ISO (YYYY-MM-DD); `topics` her satir bir konu."""
    if not _enabled():
        return {"error": "okul koprusu kapali (CYRAEN_OKUL_ENABLED=false)."}
    course = (course or "").strip()
    d = _parse_iso(exam_date)
    if not course or not d:
        return {"error": "'course' ve gecerli 'exam_date' (YYYY-MM-DD) zorunlu"}
    payload = {
        "course": course,
        "type": exam_type or "Vize",
        "date": d.isoformat(),
        "time": (exam_time or "").strip(),
        "location": (location or "").strip(),
        "topics": (topics or "").strip(),
        "done": False,
    }
    res = _append_op("add_exam", payload)
    res["eklenen"] = {"ders": course, "tur": payload["type"], "tarih": payload["date"]}
    return res
