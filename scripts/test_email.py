"""E-posta baglantisini dogrular.

    python scripts/test_email.py            # sadece okuma (IMAP)
    python scripts/test_email.py --send     # kendine bir test maili de gonderir

.env'de EMAIL_ADDRESS ve EMAIL_APP_PASSWORD tanimli olmali.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # konsol kodlama guvenligi
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.email_tools import check_email, send_email, _client  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def main() -> int:
    c = _client()
    if not c.enabled:
        print(f"[{FAIL}] E-posta yapilandirilmamis.")
        print("       .env dosyasina ekle:")
        print("         EMAIL_ADDRESS=...@gmail.com")
        print("         EMAIL_APP_PASSWORD=16haneli-uygulama-sifresi")
        print("       Gmail app password: https://myaccount.google.com/apppasswords")
        return 1

    print(f"Hesap : {c.address}")
    print(f"IMAP  : {c.imap_host}   SMTP: {c.smtp_host}:{c.smtp_port}\n")

    res = check_email(unread_only=False, limit=5)
    ok = "messages" in res
    print(f"[{PASS if ok else FAIL}] check_email -> "
          + (f"{res.get('count')} mesaj" if ok else str(res.get('error'))))
    if ok:
        for m in res["messages"][:5]:
            print(f"     • {m['date']}  {m['from'][:28]:28}  {m['subject'][:50]}")

    if "--send" in sys.argv and ok:
        sr = send_email(
            to=c.address,
            subject="JARVIS e-posta testi",
            body="Bu, JARVIS'in SMTP baglantisini dogrulamak icin gonderdigi bir test mesajidir.",
        )
        sok = sr.get("status") == "gonderildi"
        print(f"[{PASS if sok else FAIL}] send_email -> "
              + (str(sr.get("status")) if sok else str(sr.get("error"))))
        ok &= sok

    print("\n" + ("\033[92mE-POSTA HAZIR\033[0m" if ok else "\033[91mBAZI ADIMLAR BASARISIZ\033[0m"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
