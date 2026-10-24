"""E-posta araclari - hem sesli CYRAEN hem COMMUNICATIONS ajanlari kullanir.

Arka uc secimi: Gmail OAuth (tools/gmail_tool.py) yapilandirilmissa Gmail API,
degilse IMAP/SMTP (agents/integrations/email_client.py). Iki yol da ayni alan
adlarini dondurur (uid, from, from_addr, subject, date[, body]).

`send_email` disari donuk / geri alinamaz oldugundan ToolRunner uzerinden ONAY
kapisina baglanir.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from agents.integrations.email_client import EmailClient
from config.settings import get_settings
from tools import gmail_tool


@lru_cache(maxsize=1)
def _client() -> EmailClient:
    s = get_settings()
    return EmailClient(
        address=s.email_address,
        password=s.email_app_password,
        imap_host=s.email_imap_host,
        smtp_host=s.email_smtp_host,
        smtp_port=s.email_smtp_port,
        sender_name=s.email_sender_name,
    )


def _use_gmail(folder: str = "INBOX") -> bool:
    # Gmail API yalnizca gelen kutusu icin kullanilir; ozel IMAP klasorleri IMAP'te kalir
    return folder.upper() == "INBOX" and gmail_tool.gmail_enabled()


def email_enabled() -> bool:
    return gmail_tool.gmail_enabled() or _client().enabled


def check_email(unread_only: bool = True, limit: int = 10, folder: str = "INBOX") -> dict[str, Any]:
    """Gelen kutusundaki son e-postalari listeler (gonderen, konu, tarih)."""
    if _use_gmail(folder):
        return gmail_tool.list_emails(limit=int(limit), unread_only=bool(unread_only))
    return _client().list_recent(folder=folder, limit=int(limit), unseen_only=bool(unread_only))


def read_email(uid: str, folder: str = "INBOX") -> dict[str, Any]:
    """Bir e-postanin tam icerigini (govde dahil) getirir. uid check_email ciktisindan alinir."""
    if _use_gmail(folder):
        return gmail_tool.read_gmail(str(uid))
    return _client().read(str(uid), folder=folder)


def search_email(query: str, limit: int = 10, folder: str = "INBOX") -> dict[str, Any]:
    """Gelen kutusunda metin aramasi yapar."""
    if _use_gmail(folder):
        result = gmail_tool.list_emails(limit=int(limit), query=f"in:inbox {query}")
        return {"query": query, **result} if "error" not in result else result
    return _client().search(query, folder=folder, limit=int(limit))


def send_email(to: str, subject: str, body: str, cc: str = "", in_reply_to: str = "") -> dict[str, Any]:
    """Bir e-posta gonderir. (ToolRunner bunu onay kapisina baglar.)"""
    if gmail_tool.gmail_enabled():
        return gmail_tool.send_email(to=to, subject=subject, body=body, cc=cc, in_reply_to=in_reply_to)
    return _client().send(to=to, subject=subject, body=body, cc=cc, in_reply_to=in_reply_to)
