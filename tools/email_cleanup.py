"""Gelen kutusu temizligi - IMAP (Gmail) uzerinden mailleri tek tek okur, onemsizleri
Cop kutusuna tasir (kalici silme YOK; Gmail 30 gun saklar).

Akis:  collect() -> classify_rules() -> classify_llm() -> move_to_trash() -> CSV + not
Guvenlik: yildizli / Gmail 'Onemli' / son 7 gun / beyaz liste / daha once yanit verilen
adresler asla silinmez; LLM'in karar veremedigi her mail TUTULUR. Silinen her mail
data/email_cleanup/<tarih>.csv'ye yazilir; `restore(csv)` Message-ID ile geri tasir.

CLI: scripts/email_cleanup.py
"""

from __future__ import annotations

import asyncio
import csv
import html
import imaplib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable

from loguru import logger

KEEP_DAYS = 7
FETCH_CHUNK = 100
LLM_BATCH = 40

# Gonderen adresi / konu / gonderen adinda gecerse mail korunur (kucuk harf, ASCII'siz de yazildi).
_SAFE_DOMAINS = (".edu.tr", ".gov.tr", ".edu", "turkiye.gov.tr", "accounts.google.com")
_SAFE_WORDS = (
    "ziraat", "isbank", "iş bankası", "garanti", "akbank", "yapikredi", "yapı kredi", "vakif",
    "vakıf", "halkbank", "qnb", "denizbank", "enpara", "papara", "ininal", "kuveyt", "fibabanka",
    "e-devlet", "edevlet", "sgk", "osym", "ösym", "yök", "yok.gov", "universite", "üniversite",
    "şifre", "sifre", "parola", "doğrulama", "dogrulama", "güvenlik", "guvenlik", "security",
    "verification", "verify", "password", "2fa", "giriş kodu", "login code", "sign-in",
    "fatura", "invoice", "receipt", "makbuz", "dekont", "ödeme", "odeme", "payment",
    "kargo", "sipariş", "siparis", "order", "teslimat", "shipment", "bilet", "ticket",
    "randevu", "appointment", "sözleşme", "sozlesme", "noter", "vergi", "hoca", "ödev", "odev",
    "sınav", "sinav", "staj", "mülakat", "mulakat", "interview", "burs",
)


@dataclass
class Mail:
    uid: str
    sender: str = ""
    sender_addr: str = ""
    subject: str = ""
    date: datetime | None = None
    message_id: str = ""
    unsubscribe: bool = False
    flagged: bool = False
    important: bool = False
    category: str = ""  # promotions | social | updates | ""
    snippet: str = ""
    decision: str = ""  # sil | tut
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ IMAP yardimcilari
def connect() -> imaplib.IMAP4_SSL:
    from tools.email_tools import _client

    client = _client()
    if not client.enabled:
        raise RuntimeError("E-posta yapilandirilmamis (.env: EMAIL_ADDRESS / EMAIL_APP_PASSWORD).")
    return client._imap()


def special_folders(conn: imaplib.IMAP4_SSL) -> dict[str, str]:
    """LIST bayraklarindan (\\Trash, \\Sent, \\All) klasor adlari - Gmail dilinden bagimsiz."""
    out: dict[str, str] = {}
    typ, data = conn.list()
    for raw in data or []:
        line = raw.decode("ascii", "replace") if isinstance(raw, bytes) else str(raw)
        m = re.match(r'\((?P<flags>[^)]*)\)\s+"[^"]*"\s+(?P<name>.+)$', line)
        if not m:
            continue
        name = m.group("name").strip()
        for flag in ("Trash", "Sent", "All"):
            if f"\\{flag}" in m.group("flags"):
                out[flag.lower()] = name if name.startswith('"') else f'"{name}"'
    return out


def _uid_set(uids: Iterable[str]) -> str:
    return ",".join(uids)


def _chunks(seq: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _search(conn: imaplib.IMAP4_SSL, *criteria: str) -> list[str]:
    typ, data = conn.uid("SEARCH", None, *criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    return [u.decode() for u in data[0].split()]


def _decode_snippet(raw: bytes, limit: int = 300) -> str:
    """Govdenin basindan okunabilir kisa bir parca (MIME/base64 cop olabilir - en iyi caba)."""
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"=\r?\n", "", text)  # quoted-printable satir kirma
    lines = [ln for ln in text.splitlines()
             if ln.strip() and not ln.startswith(("--", "Content-")) and not re.fullmatch(r"[A-Za-z0-9+/=]{40,}", ln.strip())]
    return " ".join(" ".join(lines).split())[:limit]


def sent_addresses(conn: imaplib.IMAP4_SSL, sent_folder: str) -> set[str]:
    """Gonderilmis klasorundeki alicilar - Sezai'nin yazistigi kisiler asla silinmez."""
    out: set[str] = set()
    if conn.select(sent_folder, readonly=True)[0] != "OK":
        return out
    uids = _search(conn, "ALL")
    for chunk in _chunks(uids, 200):
        typ, data = conn.uid("FETCH", _uid_set(chunk), "(BODY.PEEK[HEADER.FIELDS (TO CC)])")
        for part in data or []:
            if isinstance(part, tuple):
                hdr = BytesParser(policy=policy.compat32).parsebytes(part[1])
                for _, addr in getaddresses(hdr.get_all("To", []) + hdr.get_all("Cc", [])):
                    if addr:
                        out.add(addr.lower())
    return out


def inbox_index(conn: imaplib.IMAP4_SSL, limit: int | None = None) -> tuple[list[str], dict[str, set[str]]]:
    """INBOX UID'leri (en eskiden) + Gmail kategori kumeleri."""
    conn.select("INBOX", readonly=True)
    uids = _search(conn, "ALL")
    if limit:
        uids = uids[:limit]
    cats = {name: set(_search(conn, "X-GM-RAW", f'"category:{name}"'))
            for name in ("promotions", "social", "updates")}
    return uids, cats


def collect(
    conn: imaplib.IMAP4_SSL, limit: int | None = None, *,
    uids: list[str] | None = None, cats: dict[str, set[str]] | None = None,
) -> list[Mail]:
    """INBOX'taki mailleri (en eskiden) okur; BODY.PEEK - okundu isareti degismez."""
    if uids is None or cats is None:
        uids, cats = inbox_index(conn, limit)
    else:
        conn.select("INBOX", readonly=True)

    mails: dict[str, Mail] = {}
    for chunk in _chunks(uids, FETCH_CHUNK):
        typ, data = conn.uid(
            "FETCH", _uid_set(chunk),
            "(UID FLAGS X-GM-LABELS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID LIST-UNSUBSCRIBE)])",
        )
        for part in data or []:
            if not isinstance(part, tuple):
                continue
            meta = part[0].decode("utf-8", "replace")
            m = re.search(r"UID (\d+)", meta)
            if not m:
                continue
            uid = m.group(1)
            hdr = BytesParser(policy=policy.default).parsebytes(part[1])
            name, addr = parseaddr(str(hdr.get("From", "")))
            try:
                date = parsedate_to_datetime(str(hdr.get("Date", "")))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, IndexError):
                date = None
            mail = Mail(
                uid=uid, sender=name or addr, sender_addr=addr.lower(),
                subject=" ".join(str(hdr.get("Subject", "")).split()),
                date=date, message_id=str(hdr.get("Message-ID", "")).strip(),
                unsubscribe=bool(hdr.get("List-Unsubscribe")),
                flagged="\\Flagged" in meta, important="\\Important" in meta,
            )
            mail.category = next((c for c, s in cats.items() if uid in s), "")
            mails[uid] = mail

        typ, data = conn.uid("FETCH", _uid_set(chunk), "(UID BODY.PEEK[TEXT]<0.1500>)")
        for part in data or []:
            if isinstance(part, tuple):
                m = re.search(r"UID (\d+)", part[0].decode("utf-8", "replace"))
                if m and m.group(1) in mails:
                    mails[m.group(1)].snippet = _decode_snippet(part[1])
        logger.info(f"[temizlik] okundu: {len(mails)}/{len(uids)}")
    return [mails[u] for u in uids if u in mails]


# ------------------------------------------------------------------ siniflandirma
def _protected(mail: Mail, replied: set[str], now: datetime) -> str:
    """Korunma gerekcesi ('' = korumasiz)."""
    if mail.flagged:
        return "yildizli"
    if mail.important:
        return "Gmail onemli isaretli"
    if mail.date is None:
        return "tarih okunamadi"
    if mail.date > now - timedelta(days=KEEP_DAYS):
        return f"son {KEEP_DAYS} gun"
    if mail.sender_addr in replied:
        return "daha once yazistigin adres"
    if mail.sender_addr.endswith(_SAFE_DOMAINS):
        return "guvenli alan adi"
    hay = f"{mail.sender} {mail.sender_addr} {mail.subject}".lower()
    word = next((w for w in _SAFE_WORDS if w in hay), "")
    if word:
        return f"beyaz liste: {word}"
    return ""


def classify_rules(mails: list[Mail], replied: set[str], now: datetime | None = None) -> list[Mail]:
    """Kesin kararlari verir; LLM'e gidecek (karari bos) mailleri dondurur."""
    now = now or datetime.now(timezone.utc)
    pending: list[Mail] = []
    for mail in mails:
        why = _protected(mail, replied, now)
        if why:
            mail.decision, mail.reason = "tut", why
        elif mail.category in ("promotions", "social") and mail.unsubscribe:
            mail.decision, mail.reason = "sil", f"{mail.category} + abonelik listesi"
        else:
            pending.append(mail)
    return pending


_LLM_SYSTEM = (
    "Sen JARVIS'in e-posta temizlik modulusun. Kullanici Sezai, bir universite ogrencisi "
    "(BOTE). Her mail icin karar ver: 'sil' = reklam, bulten, kampanya, eski/degersiz otomatik "
    "bildirim, sosyal medya bildirimi, spam benzeri. 'tut' = kisisel yazisma, okul/hoca, is/staj, "
    "hesap/guvenlik, para/fatura/siparis, resmi kurum, ileride lazim olabilecek her sey. "
    "Emin degilsen 'tut'. Sadece JSON dizi don: "
    '[{"i": <numara>, "karar": "sil"|"tut", "neden": "<en fazla 6 kelime>"}]'
)


def _llm_payload(batch: list[Mail]) -> str:
    rows = [{"i": i, "kimden": f"{m.sender} <{m.sender_addr}>", "konu": m.subject[:150],
             "kategori": m.category or "-", "abonelik_linki": m.unsubscribe,
             "ozet": m.snippet[:300]} for i, m in enumerate(batch)]
    return json.dumps(rows, ensure_ascii=False)


def apply_llm_answer(batch: list[Mail], text: str) -> None:
    """Model cevabini uygular; eksik/bozuk satirlar 'tut' olur."""
    try:
        start, end = text.index("["), text.rindex("]") + 1
        rows = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        rows = []
    answers = {r.get("i"): r for r in rows if isinstance(r, dict)}
    for i, mail in enumerate(batch):
        r = answers.get(i) or {}
        if r.get("karar") == "sil":
            mail.decision, mail.reason = "sil", f"LLM: {str(r.get('neden', ''))[:60]}"
        else:
            mail.decision = "tut"
            mail.reason = f"LLM: {str(r.get('neden', ''))[:60]}" if r else "LLM cevap vermedi"


async def classify_llm(pending: list[Mail]) -> int:
    """Kalanlari Gemini zinciriyle 40'lik partilerde siniflandirir. Islenemeyen parti sayisi."""
    from google import genai
    from google.genai import types

    from agents.genai_util import generate_with_retry
    from config.settings import get_settings

    s = get_settings()
    client = genai.Client(api_key=s.gemini_api_key,
                          http_options=types.HttpOptions(api_version=s.agents_api_version))
    config = types.GenerateContentConfig(system_instruction=_LLM_SYSTEM, temperature=0.1,
                                         response_mime_type="application/json")
    failed = 0
    for n, batch in enumerate(_chunks(pending, LLM_BATCH), 1):  # type: ignore[arg-type]
        try:
            resp = await generate_with_retry(client, model=s.agent_model_chain,
                                             contents=_llm_payload(batch), config=config, attempts=2)
            apply_llm_answer(batch, getattr(resp, "text", "") or "")
        except Exception as exc:  # noqa: BLE001 - kota/hata: parti tutulur
            failed += 1
            logger.warning(f"[temizlik] LLM partisi {n} islenemedi, tutuluyor: {exc!r}")
            for mail in batch:
                mail.decision, mail.reason = "tut", "LLM islenemedi"
        logger.info(f"[temizlik] LLM parti {n}/{(len(pending) + LLM_BATCH - 1) // LLM_BATCH}")
        await asyncio.sleep(2)
    return failed


# ------------------------------------------------------------------ tasima / geri alma
def move_to_trash(conn: imaplib.IMAP4_SSL, uids: list[str], trash: str) -> int:
    conn.select("INBOX", readonly=False)
    moved = 0
    for chunk in _chunks(uids, 200):
        typ, _ = conn.uid("MOVE", _uid_set(chunk), trash)
        if typ != "OK":  # MOVE desteklenmezse COPY + \Deleted + EXPUNGE
            typ, _ = conn.uid("COPY", _uid_set(chunk), trash)
            if typ != "OK":
                logger.error(f"[temizlik] {len(chunk)} mail tasinamadi")
                continue
            conn.uid("STORE", _uid_set(chunk), "+FLAGS", r"(\Deleted)")
            conn.expunge()
        moved += len(chunk)
    return moved


def restore(csv_path: Path) -> int:
    """CSV'deki mailleri (Message-ID ile) Cop kutusundan INBOX'a geri tasir."""
    conn = connect()
    try:
        trash = special_folders(conn).get("trash")
        if not trash:
            raise RuntimeError("Cop kutusu klasoru bulunamadi")
        conn.select(trash, readonly=False)
        back = 0
        with Path(csv_path).open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                mid = (row.get("message_id") or "").strip()
                if not mid:
                    continue
                for uid in _search(conn, "HEADER", "Message-ID", f'"{mid}"'):
                    if conn.uid("MOVE", uid, "INBOX")[0] == "OK":
                        back += 1
        return back
    finally:
        conn.logout()


# ------------------------------------------------------------------ rapor
def write_csv(path: Path, mails: list[Mail], *, append: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not (append and path.exists())
    with path.open("w" if new else "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["karar", "uid", "message_id", "tarih", "kimden", "konu", "kategori", "neden"])
        for m in mails:
            w.writerow([m.decision, m.uid, m.message_id, m.date.isoformat() if m.date else "",
                        f"{m.sender} <{m.sender_addr}>", m.subject, m.category, m.reason])
    return path


def summarize(mails: list[Mail], failed_batches: int = 0) -> str:
    sil = [m for m in mails if m.decision == "sil"]
    tut = len(mails) - len(sil)
    top: dict[str, int] = {}
    for m in sil:
        top[m.sender or m.sender_addr] = top.get(m.sender or m.sender_addr, 0) + 1
    best = ", ".join(f"{k} ({v})" for k, v in sorted(top.items(), key=lambda kv: -kv[1])[:5])
    text = f"{len(mails)} mail okundu: {len(sil)} Cop kutusuna tasindi, {tut} tutuldu."
    if best:
        text += f" En cok silinen: {best}."
    if failed_batches:
        text += f" {failed_batches} LLM partisi kota/hata nedeniyle islenemedi (o mailler tutuldu)."
    return text


def pace_delay(now: datetime, until: datetime | None, chunks_left: int) -> float:
    """Kalan sureyi kalan partilere esit yayar ('sabaha kadar agir agir'); until yoksa 0."""
    if until is None or chunks_left <= 0:
        return 0.0
    return max(0.0, (until - now).total_seconds() / chunks_left)


def _logout(conn: imaplib.IMAP4_SSL) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001
        pass


def run(
    *, dry_run: bool = False, limit: int | None = None, out_dir: Path | None = None,
    until: datetime | None = None, chunk: int = 50,
) -> dict[str, Any]:
    """Mailleri `chunk`'lik partilerde okur -> siniflar -> tasir. `until` verilirse partiler
    arasinda bekleyerek isi o saate kadar yayar; her parti icin yeni IMAP baglantisi acilir
    (uzun beklemelerde baglanti zaman asimina ugramasin)."""
    import time

    from config.settings import get_settings

    out_dir = out_dir or get_settings().data_dir / "email_cleanup"
    conn = connect()
    try:
        folders = special_folders(conn)
        trash = folders.get("trash")
        if not trash:
            raise RuntimeError("Cop kutusu klasoru bulunamadi")
        replied = sent_addresses(conn, folders["sent"]) if folders.get("sent") else set()
        uids, cats = inbox_index(conn, limit)
    finally:
        _logout(conn)
    logger.info(f"[temizlik] {len(uids)} mail, yazistigin adres: {len(replied)}, "
                f"bitis hedefi: {until:%H:%M}" if until else f"[temizlik] {len(uids)} mail")

    csv_path = out_dir / f"{datetime.now():%Y-%m-%d_%H%M}{'_deneme' if dry_run else ''}.csv"
    parts = list(_chunks(uids, max(1, chunk)))
    done: list[Mail] = []
    failed = moved = 0
    for n, part in enumerate(parts, 1):
        conn = connect()
        try:
            mails = collect(conn, uids=part, cats=cats)
            pending = classify_rules(mails, replied)
            if pending:
                failed += asyncio.run(classify_llm(pending))
            to_trash = [m.uid for m in mails if m.decision == "sil"]
            if to_trash and not dry_run:
                moved += move_to_trash(conn, to_trash, trash)
        except Exception as exc:  # noqa: BLE001 - tek parti hatasi isi durdurmaz
            logger.exception(f"[temizlik] parti {n} hatasi, atlaniyor: {exc!r}")
            mails = []
        finally:
            _logout(conn)
        write_csv(csv_path, mails, append=True)
        done.extend(mails)
        logger.info(f"[temizlik] parti {n}/{len(parts)} bitti - tasinan toplam {moved}")
        wait = pace_delay(datetime.now(), until, len(parts) - n)
        if wait and n < len(parts):
            time.sleep(wait)

    summary = summarize(done, failed)
    if dry_run:
        summary = "DENEME (hicbir sey tasinmadi): " + summary.replace("Cop kutusuna tasindi", "silinecekti")
    elif moved != sum(m.decision == "sil" for m in done):
        summary += f" (Gercekte tasinan: {moved})"
    return {"summary": summary, "csv": str(csv_path), "okunan": len(done),
            "silinecek": sum(m.decision == "sil" for m in done), "tasinan": moved,
            "islenemeyen_parti": failed}
