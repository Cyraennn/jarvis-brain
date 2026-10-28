"""Lab bilgisayarina ilk kurulum paketi hazirlar (kod + hafiza, tek zip).

Kod (jarvis-brain, `.venv`/`__pycache__`/`build`/`dist` haric) + data/ (GBrain,
hatirlatici/rutin, okul durumu, konusma gunlukleri, `config/whatsapp.json`) +
Obsidian kasasi (`JARVIS_OBSIDIAN_VAULT`) + `.env` (uzak-sunucu satirlari
otomatik eklenmis) tek bir zip'e paketler.

Ayni zamanda BU makinedeki `remote_client/.env`'i, pakete gomulenle AYNI (yeni
uretilmis veya zaten var olan) tokenlarla gunceller - boylece iki taraf elle
kopyala-yapistir hatasi olmadan eslesir. Idempotent: tekrar calistirilirsa
var olan tokenlari KORUR.

`data/whatsapp_session/` (Playwright Chrome profili, ~127MB) varsayilan olarak
HARIC tutulur (WhatsApp entegrasyonu genelde kapali); `--include-whatsapp-session`
ile dahil edilebilir. `config/whatsapp.json` (kucuk ayar dosyasi) HER ZAMAN dahildir.

Kullanim:
    python scripts/export_lab_package.py
    python scripts/export_lab_package.py --out D:\\jarvis-lab-package.zip
    python scripts/export_lab_package.py --include-whatsapp-session

Sonraki adimlar (lab bilgisayarinda): paketin icindeki README.txt VEYA
jarvis-brain/docs/remote_setup.md.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # jarvis-brain/
PROJECT_ROOT = ROOT.parent  # multi/
REMOTE_CLIENT_DIR = PROJECT_ROOT / "remote_client"
sys.path.insert(0, str(ROOT))

from config.settings import get_settings  # noqa: E402

_EXCLUDE_DIR_NAMES = {".venv", "venv", "__pycache__", "build", "dist", ".pytest_cache"}
_EXCLUDE_SUFFIXES = {".pyc"}

_REMOTE_CLIENT_ENV_ORDER = [
    "JARVIS_SERVER_HOST",
    "JARVIS_REMOTE_AUDIO_TOKEN",
    "JARVIS_WEB_TOKEN",
    "JARVIS_REMOTE_AUDIO_PORT",
    "JARVIS_WEB_PORT",
    "JARVIS_CLIENT_OPEN_BROWSER",
]


def _iter_code_files(base: Path, *, include_whatsapp_session: bool):
    """`base` (jarvis-brain koku) altindaki paketlenecek dosyalari (yol, goreli-yol)
    ciftleri olarak dolasir; disarida birakilan klasor/uzantilari atlar."""
    for path in sorted(base.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(base)
        if any(part in _EXCLUDE_DIR_NAMES for part in rel.parts):
            continue
        if path.suffix in _EXCLUDE_SUFFIXES:
            continue
        if not include_whatsapp_session and rel.parts[:2] == ("data", "whatsapp_session"):
            continue
        yield path, rel


def _parse_env_lines(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def ensure_remote_client_tokens(remote_client_dir: Path = REMOTE_CLIENT_DIR) -> tuple[str, str]:
    """`remote_client/.env`'i okur/olusturur; tokenlar zaten varsa AYNEN korunur
    (idempotent), yoksa `secrets.token_urlsafe` ile yeni uretilip yazilir."""
    env_path = remote_client_dir / ".env"
    example_path = remote_client_dir / ".env.example"

    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    elif example_path.is_file():
        lines = example_path.read_text(encoding="utf-8").splitlines()

    values = _parse_env_lines(lines)
    values["JARVIS_WEB_TOKEN"] = values.get("JARVIS_WEB_TOKEN") or secrets.token_urlsafe(24)
    values["JARVIS_REMOTE_AUDIO_TOKEN"] = (
        values.get("JARVIS_REMOTE_AUDIO_TOKEN") or secrets.token_urlsafe(24)
    )
    values.setdefault("JARVIS_SERVER_HOST", "")
    values.setdefault("JARVIS_REMOTE_AUDIO_PORT", "8771")
    values.setdefault("JARVIS_WEB_PORT", "8770")
    values.setdefault("JARVIS_CLIENT_OPEN_BROWSER", "true")

    remote_client_dir.mkdir(parents=True, exist_ok=True)
    out_lines = [f"{k}={values[k]}" for k in _REMOTE_CLIENT_ENV_ORDER]
    env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"[export] {env_path} guncellendi (mevcut tokenlar korunur, eksikler uretilir).")
    return values["JARVIS_WEB_TOKEN"], values["JARVIS_REMOTE_AUDIO_TOKEN"]


def build_lab_env_text(web_token: str, audio_token: str, env_path: Path = ROOT / ".env") -> str:
    """Mevcut `jarvis-brain/.env` icerigine uzak-sunucu satirlarini ekler.

    Ayni isimli bir satir zaten varsa dotenv'in "son satir kazanir" davranisiyla
    buradaki deger gecerli olur (bilincli - lab konfigurasyonu her zaman ustun)."""
    base = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    if not base.strip():
        print(
            "[export] UYARI: jarvis-brain/.env bulunamadi/bos - GEMINI_API_KEY vb. "
            "paketteki .env.for-lab'a elle eklenmeli."
        )
    extra = f"""
# --- scripts/export_lab_package.py tarafindan otomatik eklendi ({datetime.now():%Y-%m-%d %H:%M}) ---
JARVIS_AUDIO_MODE=network
JARVIS_WEB_TOKEN={web_token}
JARVIS_WEB_BIND=0.0.0.0
JARVIS_REMOTE_AUDIO_TOKEN={audio_token}
JARVIS_OBSIDIAN_VAULT=C:\\JARVIS\\Hafiza
"""
    return base.rstrip("\n") + "\n" + extra


def _readme_text(vault_dir: Path | None, include_whatsapp_session: bool) -> str:
    vault_line = str(vault_dir) if vault_dir else "(tanimsiz - kasa pakete eklenmedi)"
    wa_note = (
        "dahil edildi (--include-whatsapp-session)"
        if include_whatsapp_session
        else "HARIC tutuldu (varsayilan; WhatsApp entegrasyonu genelde kapali)"
    )
    return f"""JARVIS LAB PAKETI - {datetime.now():%Y-%m-%d %H:%M}

>>> Adim adim, resimli/basit anlatim icin once "1-BURADAN-BASLA.txt" dosyasini
    ac. Bu dosya (README.txt) teknik/kisa ozet, tercih ettigini kullan. <<<

Bu zip'i lab bilgisayarinda TAM OLARAK "C:\\JARVIS\\" altina cikartin (asagidaki
.env.for-lab icindeki JARVIS_OBSIDIAN_VAULT bu yolu varsayiyor):

    C:\\JARVIS\\jarvis-brain\\   <- kod + data/
    C:\\JARVIS\\Hafiza\\         <- Obsidian kasasi ("{vault_line}")

Sonra (lab bilgisayarinda, PowerShell/CMD):
    cd C:\\JARVIS\\jarvis-brain
    python -m venv .venv
    .venv\\Scripts\\activate
    pip install -r requirements.txt
    ren .env.for-lab .env
    python run_server.py

Detayli adimlar (Tailscale, guvenlik duvari, Task Scheduler, dogrulama listesi):
    jarvis-brain\\docs\\remote_setup.md

ICERIK:
  - jarvis-brain/            : tum kod + data/ (GBrain, hatirlaticilar, okul durumu,
                                 konusma gunlukleri, config/whatsapp.json).
                                 data/whatsapp_session/ {wa_note}.
  - jarvis-brain/.env.for-lab : mevcut .env + uzak-sunucu ayarlari. Tokenlar BU
                                 makinedeki remote_client/.env ile ONCEDEN eslesir -
                                 ev tarafinda sadece JARVIS_SERVER_HOST'u doldurman yeterli
                                 (Tailscale kurulduktan sonra lab'in MagicDNS adi).
  - JARVIS-Hafiza-Vault/     : Obsidian kasasinin tam kopyasi.

GUVENLIK: Bu zip GIZLI ANAHTARLAR icerir (GEMINI_API_KEY, web/ses tokenlari, varsa
e-posta uygulama sifresi, ADB kilit PIN'i). USB'yi baskasiyla paylasmayin; aktarim
sonrasi zip dosyasini (ve varsa USB'deki kopyasini) silin.
"""


def build_package(out_path: Path, *, include_whatsapp_session: bool) -> Path:
    settings = get_settings()
    vault_dir = settings.obsidian_dir

    web_token, audio_token = ensure_remote_client_tokens()
    lab_env_text = build_lab_env_text(web_token, audio_token)
    readme = _readme_text(vault_dir, include_whatsapp_session)

    simple_guide_path = ROOT / "docs" / "LAB_KURULUM_BASIT.md"
    simple_guide = (
        simple_guide_path.read_text(encoding="utf-8") if simple_guide_path.is_file() else ""
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    env_rel = Path(".env")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, rel in _iter_code_files(ROOT, include_whatsapp_session=include_whatsapp_session):
            if rel == env_rel:
                continue  # gercek .env yerine asagidaki .env.for-lab eklenir
            zf.write(path, arcname=str(Path("jarvis-brain") / rel))
        zf.writestr("jarvis-brain/.env.for-lab", lab_env_text)

        if vault_dir and vault_dir.is_dir():
            for path in sorted(vault_dir.rglob("*")):
                if path.is_dir():
                    continue
                rel = path.relative_to(vault_dir)
                zf.write(path, arcname=str(Path("JARVIS-Hafiza-Vault") / rel))
        else:
            print("[export] UYARI: Obsidian kasasi bulunamadi/tanimsiz, pakete eklenmedi.")

        zf.writestr("README.txt", readme)
        if simple_guide:
            zf.writestr("1-BURADAN-BASLA.txt", simple_guide)
        else:
            print("[export] UYARI: docs/LAB_KURULUM_BASIT.md bulunamadi, basit kilavuz eklenmedi.")

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="Cikti zip yolu")
    parser.add_argument(
        "--include-whatsapp-session",
        action="store_true",
        help="data/whatsapp_session/ (~127MB Playwright profili) da pakete eklenir",
    )
    args = parser.parse_args()

    out_path = args.out or (
        PROJECT_ROOT / f"jarvis-lab-package-{datetime.now():%Y%m%d-%H%M}.zip"
    )

    result = build_package(out_path, include_whatsapp_session=args.include_whatsapp_session)
    size_mb = result.stat().st_size / (1024 * 1024)
    print(f"[export] Hazir: {result} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
