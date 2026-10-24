"""Gmail OAuth 2.0 yetkilendirmesi (bir kez calistirilir).

    python scripts/gmail_auth.py

On kosul: Google Cloud'dan indirilen "Masaustu uygulamasi" OAuth istemci JSON'u
config/gmail_credentials.json'da (ya da .env: GMAIL_CREDENTIALS_FILE) olmali.
Tarayicida izin verdikten sonra token GMAIL_TOKEN_FILE'a (varsayilan data/gmail_token.json)
yazilir ve CYRAEN e-posta araclari otomatik olarak Gmail API'ye gecer.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import gmail_tool  # noqa: E402


def main() -> int:
    try:
        token = gmail_tool.authorize_interactive()
    except FileNotFoundError as exc:
        print(f"HATA: {exc}\nGoogle Cloud Console'dan OAuth istemci JSON'unu indirip bu yola koyun.")
        return 1
    print(f"Yetkilendirme tamam -> {token}")
    result = gmail_tool.get_unread_emails(limit=3)
    print("Test (okunmamis 3 mail):", result)
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())
