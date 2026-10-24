"""Mail kimlik hatalarinin anlasilir mesaja cevrilmesi."""

import imaplib
import smtplib

from agents.integrations.email_client import AUTH_ERROR_MSG, _auth_error, _fail


def test_imap_authenticationfailed_taninir():
    exc = imaplib.IMAP4.error("b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'")
    assert _auth_error(exc) == AUTH_ERROR_MSG


def test_smtp_535_taninir():
    exc = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
    assert _auth_error(exc) == AUTH_ERROR_MSG


def test_alakasiz_hata_eski_mesaji_korur():
    exc = TimeoutError("timed out")
    assert _auth_error(exc) is None
    assert _fail(exc, "E-posta okunamadi") == {"error": "E-posta okunamadi: timed out"}
