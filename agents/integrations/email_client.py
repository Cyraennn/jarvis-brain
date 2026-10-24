"""E-posta baglantisi (IMAP okuma + SMTP gonderme).

Yalnizca stdlib (imaplib/smtplib/email). Gmail icin: 2 adimli dogrulama ac ->
Google Hesabi > Guvenlik > Uygulama sifreleri -> 16 haneli sifreyi .env'e koy:
    EMAIL_ADDRESS=...@gmail.com
    EMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx

Anahtar yoksa tum metotlar {"error": ...} dondurur - hicbir zaman coker.
"""

from __future__ import annotations

import imaplib
import re
import smtplib
import ssl
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from loguru import logger

_PROVIDERS = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com", 465),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com", 465),
    "outlook.com": ("outlook.office365.com", "smtp.office365.com", 587),
    "hotmail.com": ("outlook.office365.com", "smtp.office365.com", 587),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com", 465),
    "yandex.com": ("imap.yandex.com", "smtp.yandex.com", 465),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com", 587),
}


def _strip(text: str, limit: int = 600) -> str:
    text = re.sub(r"\r\n?|‌", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= limit else text[:limit] + " …"


_AUTH_MARKERS = ("authenticationfailed", "invalid credentials", "username and password not accepted")

AUTH_ERROR_MSG = (
    "Mail girisi reddedildi: uygulama sifresi gecersiz veya iptal edilmis. "
    "myaccount.google.com/apppasswords adresinden yeni sifre olusturup .env icindeki "
    "EMAIL_APP_PASSWORD'u guncelleyin (veya Gmail OAuth kurun: python scripts/gmail_auth.py)."
)


def _auth_error(exc: BaseException) -> str | None:
    """Hata bir kimlik dogrulama reddi ise anlasilir mesaj dondurur, degilse None."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return AUTH_ERROR_MSG
    text = str(exc).lower()
    if any(m in text for m in _AUTH_MARKERS):
        return AUTH_ERROR_MSG
    return None


def _fail(exc: BaseException, fallback: str) -> dict[str, Any]:
    """except bloklari icin ortak donus: once kimlik hatasini, sonra genel mesaji dener."""
    auth = _auth_error(exc)
    if auth:
        logger.warning(auth)
        return {"error": auth}
    return {"error": f"{fallback}: {exc}"}


class EmailClient:
    def __init__(
        self,
        address: str = "",
        password: str = "",
        imap_host: str = "",
        smtp_host: str = "",
        smtp_port: int = 0,
        sender_name: str = "JARVIS",
    ) -> None:
        self.address = (address or "").strip()
        self.password = password or ""
        self.sender_name = sender_name or ""
        domain = self.address.split("@")[-1].lower() if "@" in self.address else ""
        d_imap, d_smtp, d_port = _PROVIDERS.get(domain, ("", "", 587))
        self.imap_host = imap_host or d_imap
        self.smtp_host = smtp_host or d_smtp
        self.smtp_port = smtp_port or d_port
        self.enabled = bool(self.address and self.password and self.imap_host and self.smtp_host)
        if self.enabled:
            logger.info(f"E-posta baglantisi hazir: {self.address} ({self.imap_host})")
        else:
            logger.info("E-posta anahtari yok - mail araclari devre disi")

    # ------------------------------------------------------------------ IMAP
    def _imap(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.imap_host, timeout=20)
        conn.login(self.address, self.password)
        return conn

    def list_recent(
        self, folder: str = "INBOX", limit: int = 12, unseen_only: bool = False
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"error": "E-posta yapilandirilmamis (.env: EMAIL_ADDRESS / EMAIL_APP_PASSWORD)."}
        try:
            conn = self._imap()
            try:
                conn.select(folder, readonly=True)
                crit = "(UNSEEN)" if unseen_only else "ALL"
                typ, data = conn.search(None, crit)
                uids = data[0].split()[-max(1, limit):]
                out: list[dict[str, Any]] = []
                for uid in reversed(uids):
                    typ, msgdata = conn.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                    if not msgdata or not isinstance(msgdata[0], tuple):
                        continue
                    hdr = BytesParser(policy=policy.default).parsebytes(msgdata[0][1])
                    frm_name, frm_addr = parseaddr(str(hdr.get("From", "")))
                    out.append({
                        "uid": uid.decode(),
                        "from": frm_name or frm_addr,
                        "from_addr": frm_addr,
                        "subject": str(hdr.get("Subject", "(konu yok)")),
                        "date": _fmt_date(hdr.get("Date", "")),
                    })
                return {"folder": folder, "count": len(out), "messages": out}
            finally:
                conn.logout()
        except imaplib.IMAP4.error as exc:
            return _fail(exc, "IMAP giris/erisim hatasi")
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "E-posta okunamadi")

    def read(self, uid: str, folder: str = "INBOX") -> dict[str, Any]:
        if not self.enabled:
            return {"error": "E-posta yapilandirilmamis."}
        try:
            conn = self._imap()
            try:
                conn.select(folder, readonly=True)
                typ, msgdata = conn.fetch(str(uid).encode(), "(RFC822)")
                if not msgdata or not isinstance(msgdata[0], tuple):
                    return {"error": f"Mesaj bulunamadi: uid {uid}"}
                msg = BytesParser(policy=policy.default).parsebytes(msgdata[0][1])
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain" and not part.is_multipart():
                            body = part.get_content()
                            break
                    if not body:
                        for part in msg.walk():
                            if part.get_content_type() == "text/html":
                                body = re.sub(r"<[^>]+>", " ", part.get_content())
                                break
                else:
                    body = msg.get_content()
                frm_name, frm_addr = parseaddr(str(msg.get("From", "")))
                return {
                    "uid": str(uid),
                    "from": frm_name or frm_addr,
                    "from_addr": frm_addr,
                    "subject": str(msg.get("Subject", "")),
                    "date": _fmt_date(msg.get("Date", "")),
                    "body": _strip(body or "", 4000),
                }
            finally:
                conn.logout()
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "Mesaj okunamadi")

    def search(self, query: str, folder: str = "INBOX", limit: int = 10) -> dict[str, Any]:
        if not self.enabled:
            return {"error": "E-posta yapilandirilmamis."}
        q = query.strip()
        try:
            conn = self._imap()
            try:
                conn.select(folder, readonly=True)
                typ, data = conn.search(None, "TEXT", f'"{q}"')
                uids = data[0].split()[-max(1, limit):]
                out = []
                for uid in reversed(uids):
                    typ, md = conn.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                    if md and isinstance(md[0], tuple):
                        hdr = BytesParser(policy=policy.default).parsebytes(md[0][1])
                        fn, fa = parseaddr(str(hdr.get("From", "")))
                        out.append({"uid": uid.decode(), "from": fn or fa,
                                    "subject": str(hdr.get("Subject", "")),
                                    "date": _fmt_date(hdr.get("Date", ""))})
                return {"query": q, "count": len(out), "messages": out}
            finally:
                conn.logout()
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "Arama basarisiz")

    # ------------------------------------------------------------------ SMTP
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        in_reply_to: str = "",
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"error": "E-posta yapilandirilmamis."}
        to = to.strip()
        if "@" not in to:
            return {"error": f"Gecersiz alici adresi: {to}"}
        msg = EmailMessage()
        msg["From"] = f"{self.sender_name} <{self.address}>" if self.sender_name else self.address
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = subject or "(konu yok)"
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body or "")
        try:
            ctx = ssl.create_default_context()
            if int(self.smtp_port) == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=20, context=ctx) as s:
                    s.login(self.address, self.password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as s:
                    s.starttls(context=ctx)
                    s.login(self.address, self.password)
                    s.send_message(msg)
            logger.info(f"E-posta gonderildi -> {to} : {subject}")
            return {"status": "gonderildi", "to": to, "subject": msg["Subject"]}
        except Exception as exc:  # noqa: BLE001
            return _fail(exc, "Gonderilemedi")


def _fmt_date(raw: object) -> str:
    try:
        dt = parsedate_to_datetime(str(raw))
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(raw)[:30]
