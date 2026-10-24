"""Obsidian vault koprusu.

JARVIS'in aldigi notlar, GBrain kayitlari ve KONUSMALAR, `.env`'de
`JARVIS_OBSIDIAN_VAULT` tanimliysa Obsidian kasasina markdown olarak yazilir.
Vault yoksa sessizce atlanir; yerel `data/` her zaman calismaya devam eder.

Yerlesim (kasa icinde; `JARVIS_OBSIDIAN_SUBDIR` bos ise dogrudan kok):
    Notlar/YYYY-MM-DD.md      -> gunluk not dosyalari (remember_note)
    GBrain/<slug>.md          -> GBrain kayit aynasi (kb_write)
    Konusmalar/YYYY-MM-DD.md  -> otomatik konusma kaydi (her tur: Sen / JARVIS)
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger

from config.settings import get_settings


def vault_dir() -> Path | None:
    """JARVIS'in yazacagi kasa klasoru; vault tanimsiz/gecersizse None."""
    return get_settings().obsidian_dir


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "").strip().lower(), flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s[:60] or "not"


def append_note(text: str) -> Path | None:
    """Gunluk not dosyasina zaman damgali bir madde ekler."""
    note = (text or "").strip()
    if not note:
        return None
    base = vault_dir()
    if base is None:
        return None
    try:
        notes_dir = base / "Notlar"
        notes_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        f = notes_dir / f"{now:%Y-%m-%d}.md"
        if not f.exists():
            f.write_text(
                f"---\ntags: [jarvis, not]\nsource: JARVIS\n---\n\n"
                f"# JARVIS Notlari - {now:%d.%m.%Y}\n\n",
                encoding="utf-8",
            )
        # cok satirli notlar (zamanli gorev sonuclari) liste maddesinin icinde kalsin
        body = note.replace("\n", "\n  ")
        with f.open("a", encoding="utf-8") as handle:
            handle.write(f"- **{now:%H:%M}** {body}\n")
        return f
    except OSError as exc:
        logger.debug(f"Obsidian not yazma hatasi: {exc}")
        return None


def read_recent_notes(limit: int = 50) -> list[str]:
    """Vault'taki gunluk not dosyalarindan son maddeleri okur."""
    base = vault_dir()
    if base is None:
        return []
    notes_dir = base / "Notlar"
    if not notes_dir.is_dir():
        return []
    out: list[str] = []
    try:
        for f in sorted(notes_dir.glob("*.md")):
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("- "):
                    out.append(line[2:].strip())
    except OSError as exc:
        logger.debug(f"Obsidian not okuma hatasi: {exc}")
        return []
    return out[-max(1, limit):]


def write_doc(
    title: str,
    content: str,
    subfolder: str = "GBrain",
    tags: list[str] | None = None,
) -> Path | None:
    """Vault icine tek bir markdown belgesi yazar (frontmatter'li)."""
    body = (content or "").strip()
    if not body:
        return None
    base = vault_dir()
    if base is None:
        return None
    try:
        folder = base / subfolder
        folder.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        tag_list = ["jarvis", subfolder.lower(), *(t.strip() for t in (tags or []) if t.strip())]
        f = folder / f"{_slug(title)}.md"
        f.write_text(
            "\n".join(
                [
                    "---",
                    f"title: {title.strip()}",
                    f"created: {now.isoformat(timespec='seconds')}",
                    f"tags: [{', '.join(dict.fromkeys(tag_list))}]",
                    "source: JARVIS GBrain",
                    "---",
                    "",
                    f"# {title.strip()}",
                    "",
                    body,
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f
    except OSError as exc:
        logger.debug(f"Obsidian belge yazma hatasi: {exc}")
        return None


# Gunluk konusma dosyasina eszamanli eklemeleri siralar.
_APPEND_LOCK = threading.Lock()

_ROLE_LABEL = {
    "user": "Sen",
    "jarvis": "JARVIS",
    "telefon": "Sen (telefon)",
    "sistem": "Sistem",
    "kopru": "Kopru",
    "hatirlatici": "Hatirlatici",
    "ajan": "Ajan",
}


def append_conversation(role: str, text: str) -> Path | None:
    """Bir konusma turunu gunluk konusma dosyasina ekler (Konusmalar/YYYY-MM-DD.md)."""
    body = " ".join((text or "").split()).strip()
    if not body:
        return None
    base = vault_dir()
    if base is None:
        return None
    try:
        conv_dir = base / "Konusmalar"
        conv_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        f = conv_dir / f"{now:%Y-%m-%d}.md"
        if not f.exists():
            f.write_text(
                "---\n"
                "tags: [jarvis, konusma, gunluk]\n"
                "source: JARVIS canli oturum\n"
                f"tarih: {now:%Y-%m-%d}\n"
                "---\n\n"
                f"# Konusma - {now:%d.%m.%Y}\n\n",
                encoding="utf-8",
            )
        label = _ROLE_LABEL.get(role, role)
        # Kullanici + JARVIS turu ayni anda ayri thread'lerden yazilir; Windows'ta
        # 'a' modu atomik degil, kilitsiz yazimlar birbirinin ustune binip satir kirpar.
        with _APPEND_LOCK, f.open("a", encoding="utf-8") as handle:
            handle.write(f"**{now:%H:%M} · {label}:** {body}\n\n")
        return f
    except OSError as exc:
        logger.debug(f"Obsidian konusma yazma hatasi: {exc}")
        return None


_MANAGED_START = "<!-- jarvis:start -->"
_MANAGED_END = "<!-- jarvis:end -->"


def write_managed_doc(
    title: str,
    content: str,
    subfolder: str,
    tags: list[str] | None = None,
    source: str = "JARVIS",
) -> Path | None:
    """JARVIS'in yonettigi bolumu gunceller, kullanicinin elle yazdiklarini korur.

    Dosya yoksa frontmatter + baslik + isaretli bolum yazilir. Varsa yalnizca
    `<!-- jarvis:start -->` ... `<!-- jarvis:end -->` arasi degisir; isaret yoksa
    (kullanici silmis) bolum dosyanin sonuna eklenir. Kitaplik notlari bunu kullanir.
    """
    body = (content or "").strip()
    base = vault_dir()
    if not body or base is None:
        return None
    block = f"{_MANAGED_START}\n{body}\n{_MANAGED_END}"
    try:
        folder = base / subfolder
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / f"{_slug(title)}.md"
        if f.is_file():
            old = f.read_text(encoding="utf-8")
            i, j = old.find(_MANAGED_START), old.find(_MANAGED_END)
            if i != -1 and j > i:
                new = old[:i] + block + old[j + len(_MANAGED_END):]
            else:
                new = old.rstrip() + "\n\n" + block + "\n"
        else:
            now = datetime.now().astimezone()
            tag_list = ["jarvis", subfolder.lower(), *(t.strip() for t in (tags or []) if t.strip())]
            new = "\n".join([
                "---",
                f"title: {title.strip()}",
                f"created: {now.isoformat(timespec='seconds')}",
                f"tags: [{', '.join(dict.fromkeys(tag_list))}]",
                f"source: {source}",
                "---",
                "",
                f"# {title.strip()}",
                "",
                block,
                "",
                "## Kendi notlarım",
                "",
            ])
        f.write_text(new, encoding="utf-8")
        return f
    except OSError as exc:
        logger.debug(f"Obsidian yonetilen belge yazma hatasi: {exc}")
        return None
