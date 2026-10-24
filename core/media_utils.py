"""WhatsApp medya yardimcilari - STT (sesli mesaj -> metin) + Vision (gorsel analiz).

CYRAEN'in ayri bir Whisper kurulumu yok; hem ses transkripsiyonu hem gorsel analiz
`agents.genai_util.generate_with_retry` uzerinden Gemini multimodal modeline
yaptirilir (model rotasyonu + retry dahil). Boylece ek bagimlilik gerekmez.

Ayrica gecici indirilen medya dosyalarini yoneten hafif bir `MediaVault` sinifi
bulunur: indirilen her dosya kayit altina alinir, islenince silinir, acilista /
periyodik olarak eski artiklar suprulur (auto-cleanup).
"""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import get_settings

# ------------------------------------------------------------------ mime tespiti

_AUDIO_MIME = {
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".oga": "audio/ogg",
    ".mp3": "audio/mp3",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".amr": "audio/amr",
    ".mp4": "audio/mp4",
}

_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def guess_audio_mime(path: Path | str) -> str:
    return _AUDIO_MIME.get(Path(path).suffix.lower(), "audio/ogg")


def guess_image_mime(path: Path | str) -> str:
    return _IMAGE_MIME.get(Path(path).suffix.lower(), "image/jpeg")


# ------------------------------------------------------------------ gemini istemci

@lru_cache(maxsize=1)
def _genai():  # noqa: ANN202
    from google import genai
    from google.genai import types

    s = get_settings()
    client = genai.Client(
        api_key=s.gemini_api_key,
        http_options=types.HttpOptions(api_version=s.agents_api_version, timeout=120_000),
    )
    return client, types


# ------------------------------------------------------------------ STT / Vision

async def transcribe_audio(path: Path | str, *, instruction: str = "") -> str:
    """Bir ses dosyasini (WhatsApp voice note dahil) metne dokturur.

    Basarisizlikta bos string doner (asla exception firlatmaz).
    """
    p = Path(path)
    if not p.is_file():
        logger.warning(f"[medya] ses dosyasi yok: {p}")
        return ""

    try:
        data = p.read_bytes()
    except OSError as exc:
        logger.warning(f"[medya] ses okunamadi: {exc!r}")
        return ""

    prompt = instruction.strip() or (
        "Bu bir WhatsApp sesli mesaji. Konusulanlari BIREBIR yaziya dok. "
        "Sadece transkript metnini ver; yorum, aciklama veya zaman damgasi ekleme. "
        "Konusma Turkce ise Turkce yaz."
    )

    try:
        from agents.genai_util import generate_with_retry

        client, types = _genai()
        s = get_settings()
        resp = await generate_with_retry(
            client,
            model=s.agent_model_chain,
            contents=[
                types.Part.from_bytes(data=data, mime_type=guess_audio_mime(p)),
                types.Part(text=prompt),
            ],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        text = (getattr(resp, "text", None) or "").strip()
        logger.info(f"[medya] transkript ({len(text)} krktr): {text[:120]}")
        return text
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[medya] transkripsiyon basarisiz: {exc!r}")
        return ""


async def describe_image(
    path: Path | str, *, caption: str = "", question: str = ""
) -> str:
    """Bir gorseli analiz edip Turkce kisa aciklama/yanit uretir.

    `caption` gonderenin resim alti yazisi, `question` ise (varsa) kullanicinin
    gorsel hakkindaki sorusudur. Basarisizlikta bos string doner.
    """
    p = Path(path)
    if not p.is_file():
        logger.warning(f"[medya] gorsel dosyasi yok: {p}")
        return ""

    try:
        data = p.read_bytes()
    except OSError as exc:
        logger.warning(f"[medya] gorsel okunamadi: {exc!r}")
        return ""

    parts_txt = [
        "Bu WhatsApp uzerinden gonderilen bir gorsel. Icerigini Turkce, kisa ve "
        "net bicimde acikla. Gereksiz uzatma."
    ]
    if caption.strip():
        parts_txt.append(f'Gonderenin resim alti yazisi: "{caption.strip()}"')
    if question.strip():
        parts_txt.append(f"Ozellikle sunu yanitla: {question.strip()}")

    try:
        from agents.genai_util import generate_with_retry

        client, types = _genai()
        s = get_settings()
        resp = await generate_with_retry(
            client,
            model=s.agent_model_chain,
            contents=[
                types.Part.from_bytes(data=data, mime_type=guess_image_mime(p)),
                types.Part(text="\n".join(parts_txt)),
            ],
            config=types.GenerateContentConfig(temperature=0.4),
        )
        text = (getattr(resp, "text", None) or "").strip()
        logger.info(f"[medya] gorsel analizi: {text[:120]}")
        return text
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[medya] gorsel analizi basarisiz: {exc!r}")
        return ""


# ------------------------------------------------------------------ gecici dosya yonetimi

class MediaVault:
    """Gecici indirilen medya dosyalari icin kayit + otomatik temizlik.

    - `path_for(name)` : indirme hedefi bir Path uretir (henuz olusturmaz)
    - `register(path)` : dosyayi takibe alir
    - `discard(path)`  : dosyayi hemen siler ve takipten cikarir
    - `sweep()`        : `retention_seconds`'tan eski TUM dosyalari siler
    """

    def __init__(
        self,
        root: Path | str,
        *,
        retention_minutes: float = 30.0,
        max_mb: float = 16.0,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = max(60.0, retention_minutes * 60.0)
        self.max_bytes = int(max(1.0, max_mb) * 1_048_576)
        self._tracked: set[Path] = set()

    def path_for(self, name: str, suffix: str = "") -> Path:
        safe = "".join(c for c in name if c.isalnum() or c in "-_.") or "media"
        stamp = f"{int(time.time() * 1000)}"
        return self.root / f"{stamp}_{safe}{suffix}"

    def register(self, path: Path | str) -> Path:
        p = Path(path)
        self._tracked.add(p)
        return p

    def too_big(self, path: Path | str) -> bool:
        try:
            return Path(path).stat().st_size > self.max_bytes
        except OSError:
            return False

    def discard(self, path: Path | str) -> None:
        p = Path(path)
        self._tracked.discard(p)
        try:
            if p.is_file():
                p.unlink()
                logger.debug(f"[medya] silindi: {p.name}")
        except OSError as exc:
            logger.debug(f"[medya] silinemedi ({p.name}): {exc!r}")

    def sweep(self) -> int:
        """Suresi gecmis dosyalari siler; silinen dosya sayisini doner."""
        removed = 0
        now = time.time()
        try:
            candidates = list(self.root.iterdir())
        except OSError:
            return 0
        for f in candidates:
            try:
                if not f.is_file():
                    continue
                if now - f.stat().st_mtime > self.retention_seconds:
                    f.unlink()
                    self._tracked.discard(f)
                    removed += 1
            except OSError:
                continue
        if removed:
            logger.info(f"[medya] auto-cleanup: {removed} eski dosya silindi.")
        return removed

    def discard_all(self) -> None:
        for p in list(self._tracked):
            self.discard(p)


def media_summary(kind: str, text: str) -> dict[str, Any]:
    """Islenen medyayi tek satirlik ozet dict'e cevirir (loglama / bridge icin)."""
    return {"kind": kind, "text": text, "chars": len(text or "")}
