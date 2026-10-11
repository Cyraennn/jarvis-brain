"""Gmail API (OAuth 2.0) araclari - okunmamislar, taslak, gonderme, uslup-taklitli yanit taslagi.

Kurulum (bir kez):
  1. Google Cloud Console -> yeni proje -> "Gmail API"yi etkinlestir.
  2. OAuth izin ekrani (External, kendi adresini test kullanicisi ekle).
  3. Kimlik bilgisi -> "OAuth istemci kimligi" -> Masaustu uygulamasi -> JSON indir
     -> config/gmail_credentials.json (ya da GMAIL_CREDENTIALS_FILE).
  4. `python scripts/gmail_auth.py` -> tarayicida izin ver -> data/gmail_token.json olusur.

Token yoksa `gmail_enabled()` False doner ve tools/email_tools.py IMAP/SMTP'ye duser.
Tum fonksiyonlar senkron ve hata durumunda {"error": ...} doner - asla coker.
"""

from __future__ import annotations

import asyncio
import base64
import re
import threading
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import get_settings

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

_LOCK = threading.Lock()
_SERVICE: Any = None


# ------------------------------------------------------------------ kimlik / servis
def _paths() -> tuple[Path, Path]:
    s = get_settings()
    return Path(s.gmail_credentials_file), Path(s.gmail_token_file)


def gmail_enabled() -> bool:
    """credentials + yetkilendirilmis token var mi (etkilesimli giris gerekmeden)."""
    cred, token = _paths()
    return cred.is_file() and token.is_file()


def _load_credentials() -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    _, token_path = _paths()
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("Gmail token gecersiz - `python scripts/gmail_auth.py` calistirin.")
    return creds


def authorize_interactive() -> Path:
    """Tarayicida OAuth izni alir ve token'i yazar (scripts/gmail_auth.py kullanir)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    cred_path, token_path = _paths()
    if not cred_path.is_file():
        raise FileNotFoundError(f"OAuth istemci dosyasi yok: {cred_path}")
    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return token_path


def _service() -> Any:
    global _SERVICE
    with _LOCK:
        if _SERVICE is None:
            from googleapiclient.discovery import build

            _SERVICE = build("gmail", "v1", credentials=_load_credentials(), cache_discovery=False)
        return _SERVICE


def _guard(fn_name: str, exc: BaseException) -> dict[str, Any]:
    logger.warning(f"Gmail {fn_name} hatasi: {exc!r}")
    return {"error": f"Gmail {fn_name} basarisiz: {type(exc).__name__}: {str(exc)[:160]}"}


def _not_configured() -> dict[str, Any]:
    return {"error": "Gmail OAuth yapilandirilmamis (config/gmail_credentials.json + "
                     "`python scripts/gmail_auth.py`)."}


# ------------------------------------------------------------------ yardimcilar
def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _fmt_date(raw: str) -> str:
    try:
        return parsedate_to_datetime(raw).astimezone().strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return raw or ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode() + b"===").decode("utf-8", errors="replace")


def _body_text(payload: dict[str, Any]) -> str:
    """text/plain tercih edilir; yoksa etiketleri ayiklanmis text/html."""
    plain, html = [], []

    def walk(part: dict[str, Any]) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html.append(re.sub(r"<[^>]+>", " ", _decode(data)))
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload)
    text = "\n".join(plain) or "\n".join(html)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _summary(msg: dict[str, Any]) -> dict[str, Any]:
    h = _headers(msg.get("payload") or {})
    name, addr = parseaddr(h.get("from", ""))
    # email_client.py ile ayni alan adlari (uid = Gmail mesaj id'si)
    return {
        "uid": msg["id"],
        "thread_id": msg.get("threadId"),
        "from": name or addr,
        "from_addr": addr,
        "subject": h.get("subject", "(konu yok)"),
        "date": _fmt_date(h.get("date", "")),
        "snippet": msg.get("snippet", ""),
    }


def _list(query: str, limit: int) -> dict[str, Any]:
    svc = _service()
    res = svc.users().messages().list(userId="me", q=query, maxResults=max(1, min(int(limit), 50))).execute()
    out = []
    for ref in res.get("messages", []):
        msg = svc.users().messages().get(
            userId="me", id=ref["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        out.append(_summary(msg))
    return {"backend": "gmail_api", "count": len(out), "messages": out}


def _build_raw(to: str, subject: str, body: str, cc: str = "",
               in_reply_to: str = "", references: str = "") -> str:
    s = get_settings()
    msg = EmailMessage()
    if s.email_address:
        msg["From"] = f"{s.email_sender_name} <{s.email_address}>" if s.email_sender_name else s.email_address
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject or "(konu yok)"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    msg.set_content(body or "")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def _reply_context(message_id: str) -> dict[str, str]:
    """Yanitlanan mesajin thread + Message-ID basliklari (zincir bozulmasin)."""
    msg = _service().users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["Message-ID", "References", "Subject", "From"],
    ).execute()
    h = _headers(msg.get("payload") or {})
    mid = h.get("message-id", "")
    return {"thread_id": msg.get("threadId", ""), "message_id": mid,
            "references": f"{h.get('references', '')} {mid}".strip(),
            "subject": h.get("subject", ""), "from": h.get("from", "")}


# ------------------------------------------------------------------ araclar
def get_unread_emails(limit: int = 10) -> dict[str, Any]:
    """Gmail gelen kutusundaki okunmamis e-postalari listeler (gonderen, konu, tarih, ozet, uid)."""
    if not gmail_enabled():
        return _not_configured()
    try:
        return _list("in:inbox is:unread", limit)
    except Exception as exc:  # noqa: BLE001
        return _guard("get_unread_emails", exc)


def list_emails(limit: int = 10, unread_only: bool = False, query: str = "") -> dict[str, Any]:
    """Genel listeleme/arama (Gmail arama sozdizimi)."""
    if not gmail_enabled():
        return _not_configured()
    q = query or ("in:inbox is:unread" if unread_only else "in:inbox")
    try:
        return _list(q, limit)
    except Exception as exc:  # noqa: BLE001
        return _guard("list_emails", exc)


def read_gmail(message_id: str) -> dict[str, Any]:
    """Bir Gmail mesajinin tam metnini getirir (message_id = get_unread_emails ciktisindaki uid)."""
    if not gmail_enabled():
        return _not_configured()
    try:
        msg = _service().users().messages().get(userId="me", id=str(message_id), format="full").execute()
        out = _summary(msg)
        body = _body_text(msg.get("payload") or {})
        out["body"] = body if len(body) <= 4000 else body[:4000] + " …"
        return out
    except Exception as exc:  # noqa: BLE001
        return _guard("read_gmail", exc)


def create_email_draft(to: str, subject: str, body: str, reply_to_id: str = "") -> dict[str, Any]:
    """Gmail'de bir e-posta TASLAGI olusturur (GONDERMEZ). reply_to_id verilirse o mesajin zincirine eklenir."""
    if not gmail_enabled():
        return _not_configured()
    to = (to or "").strip()
    if "@" not in to:
        return {"error": f"Gecersiz alici adresi: {to!r}"}
    try:
        message: dict[str, Any] = {}
        in_reply_to = references = ""
        if reply_to_id:
            ctx = _reply_context(str(reply_to_id))
            message["threadId"] = ctx["thread_id"]
            in_reply_to, references = ctx["message_id"], ctx["references"]
        message["raw"] = _build_raw(to, subject, body, in_reply_to=in_reply_to, references=references)
        draft = _service().users().drafts().create(userId="me", body={"message": message}).execute()
        return {"status": "taslak olusturuldu (gonderilmedi)", "draft_id": draft.get("id"),
                "to": to, "subject": subject}
    except Exception as exc:  # noqa: BLE001
        return _guard("create_email_draft", exc)


def send_email(to: str, subject: str, body: str, cc: str = "", in_reply_to: str = "") -> dict[str, Any]:
    """Gmail API ile e-posta gonderir. in_reply_to bir Gmail uid'si ise ayni zincirde yanitlar.
    (ToolRunner bunu onay kapisina baglar.)"""
    if not gmail_enabled():
        return _not_configured()
    to = (to or "").strip()
    if "@" not in to:
        return {"error": f"Gecersiz alici adresi: {to!r}"}
    try:
        message: dict[str, Any] = {}
        mid = references = ""
        if in_reply_to:
            if in_reply_to.startswith("<"):  # ham Message-ID basligi
                mid = references = in_reply_to
            else:                            # Gmail uid
                ctx = _reply_context(in_reply_to)
                message["threadId"] = ctx["thread_id"]
                mid, references = ctx["message_id"], ctx["references"]
        message["raw"] = _build_raw(to, subject, body, cc=cc, in_reply_to=mid, references=references)
        sent = _service().users().messages().send(userId="me", body=message).execute()
        logger.info(f"Gmail gonderildi -> {to} : {subject}")
        return {"status": "gonderildi", "backend": "gmail_api", "to": to,
                "subject": subject or "(konu yok)", "id": sent.get("id")}
    except Exception as exc:  # noqa: BLE001
        return _guard("send_email", exc)


def _style_samples(limit: int = 3) -> str:
    """Kullanicinin gonderdigi son birkac mailden kisa ornekler (uslup taklidi icin)."""
    try:
        svc = _service()
        res = svc.users().messages().list(userId="me", q="in:sent", maxResults=limit).execute()
        snippets = []
        for ref in res.get("messages", []):
            msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            text = _body_text(msg.get("payload") or {})
            # alinti kismini (> ... / "... yazdi:") at
            text = re.split(r"\n>|\n.{0,80}(?:yazdi|wrote):", text)[0].strip()
            if text:
                snippets.append(text[:500])
        return "\n---\n".join(snippets)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"uslup ornekleri alinamadi: {exc!r}")
        return ""


def _llm_reply(system: str, prompt: str) -> str:
    """Senkron baglamdan (araclar to_thread'de calisir) OpenRouter, yoksa Gemini."""
    from core.openrouter_client import OpenRouterClient, default_chain

    async def _openrouter() -> str:
        # paylasilan istemci baska bir event loop'a bagli olabilir -> burada yenisi
        client = OpenRouterClient()
        try:
            primary, *fallbacks = default_chain("gmail_draft")
            return await client.generate_response(
                prompt, system_prompt=system, model=primary, fallback_models=fallbacks,
                temperature=0.6, max_tokens=700,
            )
        finally:
            await client.client.close()

    s = get_settings()
    if s.openrouter_api_key:
        try:
            return asyncio.run(_openrouter())
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Taslak icin OpenRouter basarisiz, Gemini deneniyor: {exc!r}")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=s.gemini_api_key)
    for model in s.agent_model_chain:
        try:
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system, temperature=0.6),
            )
            if resp.text:
                return resp.text
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Gemini {model} taslak hatasi: {exc!r}")
    raise RuntimeError("Hicbir model yanit taslagi uretemedi")


def generate_auto_reply_draft(message_id: str, tone: str = "samimi", instructions: str = "") -> dict[str, Any]:
    """Bir e-postayi okuyup Sezai'nin uslubunda yanit uretir ve Gmail'e TASLAK olarak kaydeder (GONDERMEZ).
    tone: samimi | resmi | kisa. instructions: yanitta olmasi gereken ek noktalar."""
    if not gmail_enabled():
        return _not_configured()
    original = read_gmail(message_id)
    if "error" in original:
        return original
    samples = _style_samples()
    system = (
        "Sen Sezai'nin (DEU BOTE ogrencisi) e-posta asistanisin. Onun yerine, onun dogal "
        "uslubuyla Turkce (gelen mail baska dildeyse o dilde) yanit TASLAGI yaziyorsun. "
        "Yalnizca e-posta govdesini yaz (konu satiri ve aciklama ekleme). Selamlama + kisa govde + "
        "imza ('Sezai'). Bilmedigin tarih, saat, belge, taahhut UYDURMA; gerekirse [..] ile "
        "doldurulacak yer birak."
        + (f"\n\nSEZAI'NIN YAZIM ORNEKLERI (uslubu taklit et):\n{samples}" if samples else "")
    )
    prompt = (
        f"Ton: {tone}\n"
        + (f"Ek talimat: {instructions}\n" if instructions else "")
        + f"\nGELEN E-POSTA\nKimden: {original['from']} <{original['from_addr']}>\n"
          f"Konu: {original['subject']}\n\n{original.get('body', '')[:3500]}"
    )
    try:
        reply = _llm_reply(system, prompt).strip()
    except Exception as exc:  # noqa: BLE001
        return _guard("generate_auto_reply_draft", exc)
    subject = original["subject"] or ""
    if not subject.lower().startswith(("re:", "ynt:")):
        subject = f"Re: {subject}"
    draft = create_email_draft(original["from_addr"], subject, reply, reply_to_id=str(message_id))
    if "error" in draft:
        return {**draft, "reply_text": reply}
    return {**draft, "reply_text": reply,
            "note": "Taslak Gmail'e kaydedildi, GONDERILMEDI. Kullaniciya okuyup onay al."}
