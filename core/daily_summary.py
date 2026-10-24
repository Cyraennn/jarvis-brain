"""Gun sonu ozeti: o gunun konusmalari, notlari ve ajan gorevlerinden kisa bir gunluk.

Cikti `<kasa>/Gunluk/YYYY-MM-DD.md` (Ozet / Yapilanlar / Acik kalanlar / Notlar). Ertesi sabahki
brifing "Acik kalanlar"i, temiz acilan canli oturum da ozeti buradan okur
(`core/session_context.py`).

Ham konusma dokumu YALNIZ Gemini'ye (zaten sesi duyan saglayici) ve o dusunce yerel modele
gider; OpenRouter'in ucretsiz modellerine gonderilmez.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from loguru import logger

SECTIONS = ("Özet", "Yapılanlar", "Açık kalanlar", "Notlar")
MAX_CONVERSATION_CHARS = 24_000
_HEAD_CHARS = 8_000

SYSTEM_PROMPT = (
    "Sen CYRAEN'sin, Sezai'nin kisisel asistani. Sana bir gunun ham kayitlari JSON olarak "
    "verilecek: 'konusma' (sesli/yazili konusma dokumu), 'notlar', 'gorevler' (ajan gorevleri), "
    "'hatirlaticilar'. Bunlardan Turkce, kisa bir GUN SONU OZETI yaz. Tam olarak su dort "
    "Markdown basligini, bu sirayla kullan:\n"
    "## Özet\n## Yapılanlar\n## Açık kalanlar\n## Notlar\n"
    "Özet 2-4 cumle olsun; diger bolumler kisa maddeler ('- '). 'Açık kalanlar'a yalnizca "
    "gercekten yarim kalan, sonuclanmayan ya da Sezai'nin 'sonra' dedigi isleri yaz. Bir bolum "
    "icin bilgi yoksa altina yalnizca '- yok' yaz. Dokumde mikrofonun yanlislikla yakaladigi "
    "ortam konusmalari olabilir (baglamsiz, yarim cumleler): bunlari YOK SAY. Kayitlarda olmayan "
    "hicbir seyi uydurma; emin olmadigin seyi yazma."
)


def summary_path(base: Path, day: date) -> Path:
    return base / "Gunluk" / f"{day:%Y-%m-%d}.md"


def _clip_conversation(text: str) -> str:
    if len(text) <= MAX_CONVERSATION_CHARS:
        return text
    tail = MAX_CONVERSATION_CHARS - _HEAD_CHARS
    return text[:_HEAD_CHARS] + "\n[... gunun ortasi kisaltildi ...]\n" + text[-tail:]


def _body_without_frontmatter(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    return text.strip()


def collect_day_facts(day: date, *, vault: Path | None, data_dir: Path) -> dict[str, Any]:
    """Bir gunun ham kayitlari. Her kaynak bagimsizdir; olmayan/okunamayan atlanir."""
    facts: dict[str, Any] = {"tarih": f"{day:%d.%m.%Y}"}
    stamp = f"{day:%Y-%m-%d}"
    if vault is not None:
        conv = _body_without_frontmatter(vault / "Konusmalar" / f"{stamp}.md")
        conv = "\n".join(ln for ln in conv.splitlines() if ln.strip() and not ln.startswith("# "))
        if conv:
            facts["konusma"] = _clip_conversation(conv)
        notes = _body_without_frontmatter(vault / "Notlar" / f"{stamp}.md")
        note_lines = [ln for ln in notes.splitlines() if ln.strip() and not ln.startswith("# ")]
        if note_lines:
            facts["notlar"] = "\n".join(note_lines)[:6000]

    tasks: dict[str, dict[str, str]] = {}
    try:
        with (data_dir / "task_logs.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not str(row.get("updated_at", "")).startswith(stamp):
                    continue
                if row.get("status") not in ("done", "failed", "error", "blocked"):
                    continue
                tasks[str(row.get("id"))] = {  # ayni gorevin son durumu kalir
                    "ajan": str(row.get("agent", "?")), "durum": str(row.get("status")),
                    "sonuc": " ".join(str(row.get("result") or row.get("detail") or "").split())[:240],
                }
    except OSError:
        pass
    if tasks:
        facts["gorevler"] = list(tasks.values())[-40:]

    try:
        items = json.loads((data_dir / "reminders.json").read_text(encoding="utf-8"))
        fired = [f"{r['fire_at'][11:16]} {r.get('text', '')}" for r in items
                 if str(r.get("fire_at", "")).startswith(stamp)]
        if fired:
            facts["hatirlaticilar"] = fired
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return facts


def has_content(facts: dict[str, Any]) -> bool:
    return any(key in facts for key in ("konusma", "notlar", "gorevler", "hatirlaticilar"))


def template_summary(facts: dict[str, Any]) -> str:
    """Model kullanilamazsa: yorum katmadan sayilar ve ham maddeler."""
    turns = len((facts.get("konusma") or "").splitlines())
    tasks = facts.get("gorevler") or []
    done = [f"- {t['ajan']}: {t['sonuc'] or t['durum']}" for t in tasks if t["durum"] == "done"]
    open_ = [f"- {t['ajan']} ({t['durum']}): {t['sonuc']}" for t in tasks if t["durum"] != "done"]
    notes = [ln if ln.startswith("- ") else f"- {ln}"
             for ln in (facts.get("notlar") or "").splitlines() if not ln.startswith("  ")]
    notes += [f"- Hatirlatici {r}" for r in facts.get("hatirlaticilar") or []]

    def block(lines: list[str]) -> str:
        return "\n".join(lines[:15]) or "- yok"

    return (f"## Özet\nOtomatik ozet uretilemedi (model kullanilamadi). {turns} konusma satiri, "
            f"{len(tasks)} ajan gorevi kaydedildi.\n\n## Yapılanlar\n{block(done)}\n\n"
            f"## Açık kalanlar\n{block(open_)}\n\n## Notlar\n{block(notes)}")


def normalize(text: str) -> str:
    """Model ciktisini dort basliga oturtur (baslik koymadiysa tamami Ozet sayilir)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?|\n?```$", "", text).strip()
    if "## " not in text:
        text = f"## Özet\n{text}"
    for name in SECTIONS:
        if not re.search(rf"^## {re.escape(name)}\s*$", text, flags=re.MULTILINE):
            text += f"\n\n## {name}\n- yok"
    return text


def read_section(path: Path, name: str) -> str:
    """Ozet dosyasindan tek bir bolumun govdesi ('- yok' ise bos)."""
    body = _body_without_frontmatter(path)
    match = re.search(rf"^## {re.escape(name)}\s*$(.*?)(?=^## |\Z)", body,
                      flags=re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    text = match.group(1).strip()
    return "" if text.lower() in ("- yok", "yok", "") else text


def write_summary(base: Path, day: date, body: str, *, model: str = "") -> Path:
    path = summary_path(base, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    path.write_text(
        "---\n"
        "tags: [cyraen, gunluk, ozet]\n"
        "source: CYRAEN gun sonu ozeti\n"
        f"tarih: {day:%Y-%m-%d}\n"
        f"olusturuldu: {now.isoformat(timespec='seconds')}\n"
        f"model: {model or 'sablon'}\n"
        "---\n\n"
        f"# Gün sonu özeti - {day:%d.%m.%Y}\n\n{body.strip()}\n",
        encoding="utf-8",
    )
    return path


async def compose(settings: Any, facts: dict[str, Any]) -> tuple[str, str]:
    """(ozet metni, kullanilan model). Gemini -> (icinde) yerel model -> sablon."""
    from agents.genai_util import quick_text

    prompt = json.dumps(facts, ensure_ascii=False, default=str)
    text, model = await quick_text(settings, SYSTEM_PROMPT, prompt, temperature=0.3)
    if text:
        return normalize(text), model
    return template_summary(facts), ""


async def run(settings: Any, day: date, *, vault: Path | None = None) -> Path | None:
    """Gunun ozetini uretip kasaya yazar. Kayit yoksa / kasa yoksa None."""
    base = vault if vault is not None else settings.obsidian_dir
    if base is None:
        logger.debug("Gun sonu ozeti: Obsidian kasasi tanimli degil.")
        return None
    facts = collect_day_facts(day, vault=base, data_dir=settings.data_dir)
    if not has_content(facts):
        logger.debug(f"Gun sonu ozeti: {day} icin kayit yok.")
        return None
    body, model = await compose(settings, facts)
    path = write_summary(base, day, body, model=model)
    logger.info(f"Gun sonu ozeti yazildi: {path.name} ({model or 'sablon'})")
    return path


def missing_for(settings: Any, day: date) -> bool:
    """O gunun konusmasi/notu var ama ozeti yok mu (telafi gerekli mi)?"""
    base = settings.obsidian_dir
    if base is None or summary_path(base, day).exists():
        return False
    stamp = f"{day:%Y-%m-%d}.md"
    return (base / "Konusmalar" / stamp).is_file() or (base / "Notlar" / stamp).is_file()
