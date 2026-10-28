"""WhatsApp Web otomasyon modulu - JARVIS'in WhatsApp kolu.

Playwright (kalici tarayici oturumu) uzerinden `web.whatsapp.com`'a baglanir,
okunmamis sohbetleri tarar, gelen mesaji (metin / sesli mesaj / gorsel) isler,
JARVIS'in LLM'i ile bir yanit uretir ve insan gibi ("yaziyor..." + gecikme)
geri gonderir.

Tasarim ilkeleri
----------------
* **Ana beyni asla cokertmez.** `run()` tum hatalari yutar, oturum koparsa
  exponential-benzeri gecikmeyle yeniden baglanir. `main.py` bunu `BrainEngine`
  ile ayni `asyncio.TaskGroup` icinde calistirir.
* **Modulerlik.** LLM cagrisi `agents.genai_util`, STT/Vision `core.media_utils`,
  bildirim `agents.integrations.notifier` uzerinden - hepsi opsiyonel.
* **Rol tabanli yetki.** admin / whitelist / others. `others` yoksayilir.
* **Yonetici komutlari.** Admin numarasindan "JARVIS durum", "JARVIS modu ...",
  "JARVIS sessiz", "JARVIS mikrofon kapat" vb. ile sistem uzaktan yonetilir.
* **Kopru aynasi.** Gelen/giden her mesaj `bridge/outbox.txt`'e `[WHATSAPP] ...`
  olarak yazilir; canli sesli beyin olan biteni "duyar".

NOT (WhatsApp Web DOM kirilganligi): WhatsApp Web sinif/aria isimlerini sik
degistirir. Selektorler tek bir yerde - `SEL` sozlugu - toplanmistir; bir sey
calismazsa once orayi guncelleyin. Her DOM erisimi defansif sekilde sarilmistir.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import APP_DIR, BASE_DIR, Settings
from core.media_utils import MediaVault, describe_image, transcribe_audio

# ============================================================ selektorler (tek nokta)

SEL: dict[str, str] = {
    # uygulama yuklendi mi (sol sohbet paneli)
    "app_ready": "#pane-side",
    # QR giris ekrani
    "qr": 'canvas[aria-label*="Scan"], div[data-ref] canvas, canvas[role="img"]',
    # sol paneldeki sohbet satirlari
    "chat_rows": "#pane-side div[role='listitem']",
    # okunmamis rozeti (satir icinde)
    "unread_badge": 'span[aria-label*="unread"], span[aria-label*="okunmam"]',
    # acik sohbetin ust basligindaki kisi/grup adi
    "header_title": "header span[title]",
    # grup ikonu
    "group_icon": 'header span[data-icon="default-group"], header span[data-icon="group"]',
    # gelen / giden balonlar
    "msg_in": "div.message-in",
    "msg_out": "div.message-out",
    # balon icindeki metin
    "msg_text": "span.selectable-text",
    # sesli mesaj gostergeleri
    "voice_marker": (
        'span[data-icon="audio-play"], span[data-icon="ptt-status"], '
        'button[aria-label*="voice"], button[aria-label*="Sesli"]'
    ),
    # gorsel / blob resim
    "image_marker": 'img[src^="blob:"]',
    # mesaj baglam menusu (balon uzerine gelince cikan ok)
    "msg_context": 'span[data-icon="down-context"], span[data-icon="menu-alt"]',
    # dogrudan indirme ikonu (bazi medyalarda)
    "download_icon": (
        'span[data-icon="audio-download"], span[data-icon="download"], '
        'div[aria-label="Download"], div[aria-label="Indir"], div[aria-label="Indir "]'
    ),
    # baglam menusu icindeki "Indir" ogesi
    "menu_download": 'li[data-animate-dropdown-item] div[aria-label*="Download"], '
    'div[role="button"]:has-text("Download"), div[role="button"]:has-text("Indir")',
    # mesaj yazma kutusu
    "input_box": (
        'footer div[contenteditable="true"][data-tab="10"], '
        'footer div[contenteditable="true"], div[contenteditable="true"][data-tab="10"]'
    ),
    # gonder butonu
    "send_btn": 'button[aria-label="Send"], button[aria-label="Gonder"], '
    'span[data-icon="send"], button[data-tab="11"]',
}

WA_URL = "https://web.whatsapp.com"


# ============================================================ enum / rol

class Role(str, Enum):
    ADMIN = "admin"
    WHITELIST = "whitelist"
    OTHER = "other"


class Mode(str, Enum):
    AUTO = "otomatik"   # tum whitelist'e otomatik yanit
    MANUAL = "manuel"   # sadece admin'e yanit, digerleri admin'e bildirilir
    SILENT = "sessiz"   # hicbir yanit gonderilmez (yalnizca loglar/ayna)


# ============================================================ durust yanit kurallari

# `whatsapp.json` icindeki system_prompt bunu EZMEZ: her zaman sonuna eklenir.
HONESTY_RULES = (
    "DURUSTLUK KURALLARI (her zaman gecerli): "
    "1) Karsi taraf icten bir sekilde 'bot musun / gercek misin / yapay zeka misin / sen kimsin' "
    "diye sorarsa ASLA insan oldugunu soyleme; kisaca Sezai'nin yapay zeka asistani oldugunu, "
    "onun adina yazdigini belirt. "
    "2) Sezai adina soz verme, plan yapma ya da taahhutte bulunma (gelirim, ararim, atarim, "
    "bulusuruz, yaparim gibi). "
    "3) Saat, yer, sonuc, dosya, ders notu gibi bilmedigin hicbir seyi UYDURMA; bilmiyorsan "
    "'Sezai'ye ileteyim, musait olunca doner' de."
)

# Yonetici komutu on eki: "JARVIS durum", "/jarvis sessiz"; kisa sureli eski ad "cyraen ..." da kabul
_ADMIN_PREFIX_RE = re.compile(r"^/?(?:jarvis|cyraen)(?:[:,\s]+|$)", re.IGNORECASE)
_TR_ASCII = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")

# "nerdesin", "napiyosun", "musait misin", "gelecek misin" ... (ASCII'ye indirgenmis metinde aranir)
_PERSONAL_RX = re.compile(
    r"(?<![a-z])(?:"
    r"ner+de(?:sin|siniz)|nere+de(?:sin|siniz)|nerelerde(?:sin)?|nereye gittin|nereye gidiyorsun|"
    r"ne yap[i]?yor?sun|ne yap[i]?yosun|nap[i]?yor?sun|nap[i]?yosun|naptin|"
    r"musait misin|musaitsen|musait mi|uygun musun|"
    r"gelecek misin|geliyor musun|gelir misin|ne zaman gel[i]?rsin|ne zaman geliyorsun|ne zaman donersin|"
    r"kiminlesin|kimlesin|yaninda kim var"
    r")(?![a-z])"
)


# Tek basina "nerde?" / "nerede" (cumlenin tamami) da kisisel soru; "nerede yapiliyor mac" degil
_PERSONAL_ALONE_RX = re.compile(r"^\s*ner+e?de\s*[?!.]*\s*$")


def normalize_tr(text: str) -> str:
    """Kucuk harf + Turkce karakterleri ASCII'ye indirger (regex eslemesi icin)."""
    return (text or "").translate(_TR_ASCII).lower()


# ============================================================ konfigurasyon

@dataclass
class WhatsAppConfig:
    enabled: bool = False
    headless: bool = False
    user_data_dir: Path = APP_DIR / "data" / "whatsapp_session"
    download_dir: Path = APP_DIR / "data" / "whatsapp_media"

    poll_interval_seconds: float = 4.0
    history_size: int = 12
    cooldown_seconds: float = 8.0

    typing_delay_enabled: bool = True
    typing_min_seconds: float = 2.0
    typing_max_seconds: float = 6.0

    # "list"  -> yalnizca allowed_contacts
    # "all"   -> admin disindaki herkes whitelist
    # "off"   -> yalnizca admin'e yanit
    whitelist_mode: str = "list"
    admin_numbers: list[str] = field(default_factory=list)
    allowed_contacts: list[str] = field(default_factory=list)
    blacklisted_words: list[str] = field(default_factory=list)

    media_enabled: bool = True
    media_max_mb: float = 16.0
    media_retention_minutes: float = 30.0

    reply_to_groups: bool = False
    startup_mode: str = "otomatik"

    # Gelen mesaj guncel/olgusal bir soru iceriyorsa Gemini Google aramasi kullanabilsin
    web_search_enabled: bool = True

    # "nerdesin / musait misin / gelecek misin" gibi kisisel sorularda yonetici (sen) bilgilendirilir
    notify_personal_questions: bool = True

    # Yanit uretimi (dusunme) saglayicisi:
    #   "auto"       -> OpenRouter yapilandirildiysa once o, hata olursa Gemini yedegi
    #   "openrouter" -> yalnizca OpenRouter
    #   "gemini"     -> yalnizca Gemini
    # Anahtar `.env` icinde OPENROUTER_API_KEY; model burada ya da env OPENROUTER_MODEL.
    reply_provider: str = "auto"
    openrouter_model: str = ""
    openrouter_fallback_models: list[str] = field(default_factory=list)

    # Her turda listenin en ustundeki kac sohbet kontrol edilsin (WhatsApp en son
    # hareket eden sohbeti tepeye tasir). Okunmamis rozeti OLMASA da bakilir -
    # bot yeni-mesaj bildirimine degil, sohbetteki son mesaja gore karar verir.
    scan_top_chats: int = 8

    system_prompt: str = (
        "Sen WhatsApp uzerinden kullanicin adina yanit veren JARVIS'sin. "
        "Kullanicinin uslubunu benimse, yanitlari kisa, dogal ve samimi tut. "
        "Karsi taraf art arda birden fazla mesaj attiysa bunlar sana TEK bir mesaj olarak "
        "birlestirilip verilir; hepsini oku ve TEK bir mesajla, akici ve kisa bir sekilde "
        "cevap ver; sorulan hicbir soruyu yanitsiz birakma. "
        "Konusmayi aceleyle kapatmaya calisma, 'tamam', 'anlasildi', 'gorusuruz' gibi "
        "gecistiren tek kelimelik kapanislar verme - karsindaki ne yazdiysa ona gercekten cevap ver. "
        "WhatsApp emoji kullanimini abartmadan, yerinde yap. Gereksiz resmi dil kurma, "
        "gercek bir insan gibi yaz. Bilmedigin bir sey sorulursa uydurma."
    )

    # ---- yukleme -------------------------------------------------------------

    @classmethod
    def load(cls, settings: Settings | None = None) -> "WhatsAppConfig":
        """`config/whatsapp.json` (yoksa `whatsapp.example.json`) + env override."""
        cfg = cls()
        for name in ("whatsapp.json", "whatsapp.example.json"):
            for base in (APP_DIR / "config", BASE_DIR / "config"):
                path = base / name
                if path.is_file():
                    try:
                        raw = json.loads(path.read_text(encoding="utf-8"))
                        cfg._apply(raw)
                        logger.info(f"[WA] konfig yuklendi: {path}")
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.error(f"[WA] konfig okunamadi ({path}): {exc!r}")
                    break
            else:
                continue
            break

        # env override
        env_enabled = os.getenv("JARVIS_WHATSAPP_ENABLED")
        if env_enabled is not None:
            cfg.enabled = env_enabled.strip().lower() in {"1", "true", "yes", "on", "evet"}
        if os.getenv("JARVIS_WHATSAPP_HEADLESS"):
            cfg.headless = os.getenv("JARVIS_WHATSAPP_HEADLESS", "").lower() in {"1", "true", "yes", "on"}

        cfg._resolve_paths()
        return cfg

    def _apply(self, raw: dict[str, Any]) -> None:
        for key, value in raw.items():
            if key.startswith("_"):  # _comment vb.
                continue
            if hasattr(self, key):
                setattr(self, key, value)

    def _resolve_paths(self) -> None:
        base = APP_DIR
        self.user_data_dir = Path(self.user_data_dir)
        self.download_dir = Path(self.download_dir)
        if not self.user_data_dir.is_absolute():
            self.user_data_dir = base / self.user_data_dir
        if not self.download_dir.is_absolute():
            self.download_dir = base / self.download_dir
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)


# ============================================================ kisa sureli hafiza

class ConversationMemory:
    """Kisi bazli son N mesaji tutar (role: 'user' | 'assistant')."""

    def __init__(self, max_turns: int = 12) -> None:
        self.max_turns = max(2, max_turns)
        self._store: dict[str, list[dict[str, str]]] = {}

    def add(self, contact: str, role: str, text: str) -> None:
        if not text.strip():
            return
        buf = self._store.setdefault(contact, [])
        buf.append({"role": role, "text": text.strip()})
        if len(buf) > self.max_turns:
            del buf[: len(buf) - self.max_turns]

    def history(self, contact: str) -> list[dict[str, str]]:
        return list(self._store.get(contact, []))

    def clear(self, contact: str | None = None) -> None:
        if contact is None:
            self._store.clear()
        else:
            self._store.pop(contact, None)

    @property
    def contacts(self) -> int:
        return len(self._store)


# ============================================================ ana handler

class WhatsAppHandler:
    def __init__(
        self,
        settings: Settings,
        config: WhatsAppConfig | None = None,
        *,
        engine: Any = None,
        notifier: Any = None,
    ) -> None:
        self.settings = settings
        self.cfg = config or WhatsAppConfig.load(settings)
        self.engine = engine  # BrainEngine (opsiyonel) - yonetici komutlari icin

        self._notifier = notifier
        if self._notifier is None:
            try:
                from agents.integrations.notifier import Notifier

                self._notifier = Notifier(settings.ntfy_topic, settings.ntfy_server)
            except Exception:  # noqa: BLE001
                self._notifier = None

        self._memory = ConversationMemory(self.cfg.history_size)
        self._media = MediaVault(
            self.cfg.download_dir,
            retention_minutes=self.cfg.media_retention_minutes,
            max_mb=self.cfg.media_max_mb,
        )

        try:
            self.mode = Mode(self.cfg.startup_mode)
        except ValueError:
            self.mode = Mode.AUTO

        self._stop = asyncio.Event()
        self._ctx: Any = None
        self._last_reply_at: dict[str, float] = {}
        self._retry_after: dict[str, float] = {}  # yanit uretilemeyince kisa sure bekle
        self._ignored: set[str] = set()  # yetkisiz / grup - tekrar acilmaz
        self._qr_notified = False
        self._started_at = time.time()
        self._bridge_path: Path = settings.bridge_outbox_path
        self._blacklist_rx = self._compile_blacklist(self.cfg.blacklisted_words)
        # proaktif gonderim kuyrugu: (numara, metin, future). Sayfaya yalnizca yoklama
        # dongusu dokunur; disaridan gelen istekler buradan sirayla islenir.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._outgoing: asyncio.Queue[tuple[str, str, asyncio.Future[bool]]] | None = None

    # -------------------------------------------------------------- yasam dongusu

    def request_shutdown(self) -> None:
        logger.info("[WA] kapatma istegi alindi.")
        self._stop.set()

    async def run(self) -> None:
        """Ust seviye dongu - ASLA exception firlatmaz."""
        if not self.cfg.enabled:
            logger.info("[WA] devre disi (config.enabled=false) - handler baslamadi.")
            return

        try:
            import playwright.async_api  # noqa: F401
        except Exception:  # noqa: BLE001
            logger.error(
                "[WA] playwright kurulu degil. Kurulum: "
                "`pip install playwright` ve `playwright install chromium`. Handler pasif."
            )
            return

        logger.success(f"[WA] WhatsApp handler basliyor (mod: {self.mode.value}).")
        self._loop = asyncio.get_running_loop()
        self._outgoing = asyncio.Queue()
        self._media.sweep()

        backoff = 5.0
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = 5.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[WA] oturum hatasi: {exc!r}")
            finally:
                self._media.discard_all()

            if self._stop.is_set():
                break
            logger.warning(f"[WA] {backoff:.0f}s sonra yeniden baglanilacak.")
            await self._sleep_or_stop(backoff)
            backoff = min(60.0, backoff * 1.8)

        logger.info("[WA] handler durdu.")

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=max(0.1, seconds))
        except asyncio.TimeoutError:
            pass

    # -------------------------------------------------------------- tarayici oturumu

    async def _session(self) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            self._ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(self.cfg.user_data_dir),
                headless=self.cfg.headless,
                accept_downloads=True,
                viewport={"width": 1320, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            try:
                page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
                page.set_default_timeout(15_000)
                await page.goto(WA_URL, wait_until="domcontentloaded")

                if not await self._ensure_login(page):
                    return

                logger.success("[WA] WhatsApp Web hazir, mesajlar dinleniyor.")
                self._mirror_to_bridge("[WHATSAPP BILDIRIMI] WhatsApp kolu baglandi.")
                self._qr_notified = False
                await self._poll_loop(page)
            finally:
                with_ctx = self._ctx
                self._ctx = None
                try:
                    await with_ctx.close()
                except Exception:  # noqa: BLE001
                    pass

    async def _ensure_login(self, page: Any) -> bool:
        """Sohbet paneli gorunene kadar bekler. QR gerekiyorsa admin'e bildirir."""
        deadline = time.time() + 180.0
        while not self._stop.is_set() and time.time() < deadline:
            try:
                if await page.locator(SEL["app_ready"]).count() > 0:
                    return True
                if await page.locator(SEL["qr"]).count() > 0 and not self._qr_notified:
                    self._qr_notified = True
                    logger.warning("[WA] QR kodu bekleniyor - telefondan tarat.")
                    await self._notify_admin(
                        "WhatsApp QR", "web.whatsapp.com QR kodunu telefondan okut."
                    )
            except Exception:  # noqa: BLE001
                pass
            await self._sleep_or_stop(3.0)

        if not self._stop.is_set():
            logger.error("[WA] giris zaman asimi (QR taranmadi?).")
        return False

    # -------------------------------------------------------------- ana tarama

    async def _poll_loop(self, page: Any) -> None:
        while not self._stop.is_set():
            try:
                await self._drain_outgoing(page)
                await self._scan_chats(page)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[WA] tarama hatasi: {exc!r}")
            await self._sleep_or_stop(self.cfg.poll_interval_seconds)

    async def _scan_chats(self, page: Any) -> None:
        """Listenin en ustundeki N sohbeti gezer. Okunmamis rozetine BAKMAZ;
        sohbeti acar ve son mesaj karsi taraftansa (son balon `message-in`) yanitlar.
        Boylece telefondan okunmus / bildirimi dusmus mesajlar da yakalanir."""
        rows = page.locator(SEL["chat_rows"])
        try:
            total = await rows.count()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[WA] sohbet listesi okunamadi: {exc!r}")
            return
        limit = min(self.cfg.scan_top_chats, total)

        for idx in range(limit):
            if self._stop.is_set():
                return
            row = rows.nth(idx)
            try:
                if not await self._row_should_open(row):
                    continue
                # Daha once yetkisiz/grup diye elenen sohbeti tekrar acma
                # (bos yere okundu bilgisi gondermeyelim).
                name = await self._row_name(row)
                if name and name in self._ignored:
                    continue
                await row.click(timeout=5_000)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[WA] sohbet acilamadi (#{idx}): {exc!r}")
                continue
            await page.wait_for_timeout(650)
            try:
                await self._process_open_chat(page)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[WA] sohbet islenemedi: {exc!r}")
            await page.wait_for_timeout(250)

    async def _row_name(self, row: Any) -> str:
        try:
            loc = row.locator("span[title]").first
            if await loc.count() == 0:
                return ""
            return ((await loc.get_attribute("title")) or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    async def _row_should_open(self, row: Any) -> bool:
        """Sohbeti acmaya deger mi? Okunmamis rozeti varsa evet; son mesaj bize
        aitse (onizlemede gonderim tiki) hayir; belirsizse evet (acip son balona bak)."""
        try:
            if await row.locator(SEL["unread_badge"]).count() > 0:
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            own = row.locator(
                'span[data-icon="msg-check"], span[data-icon="msg-dblcheck"], '
                'span[data-icon="msg-dblcheck-ack"], span[data-icon="msg-time"]'
            )
            if await own.count() > 0:
                return False  # son mesaj bizden - yanitlanacak bir sey yok
        except Exception:  # noqa: BLE001
            pass
        return True

    async def _process_open_chat(self, page: Any) -> str | None:
        """Acik sohbeti isler. Ele alinan kisi adini dondurur (kimlik yoksa None)."""
        contact = await self._chat_identity(page)
        if not contact:
            logger.debug("[WA] kisi kimligi okunamadi, atlaniyor.")
            return None

        role = self._role_for(contact)
        if role is Role.OTHER:
            logger.info(f"[WA] yoksayildi (yetkisiz): {contact}")
            self._ignored.add(contact)
            return contact

        if await self._is_group(page) and not self.cfg.reply_to_groups:
            logger.info(f"[WA] grup atlandi: {contact}")
            self._ignored.add(contact)
            return contact

        # Yanit uretilemeyen sohbeti kisa sure atla (her poll'da LLM'i yormamak icin).
        retry_at = self._retry_after.get(contact, 0.0)
        if retry_at and time.time() < retry_at:
            return contact

        # Sohbetteki son balon(lar)a bak: kendi son mesajimiza (message-out) kadar
        # olan gelen mesajlar = yanitlanmamis. Son balon bizden ise liste bostur.
        msgs = await self._read_incoming_batch(page)
        if not msgs:
            logger.debug(f"[WA] {contact}: son mesaj bizden / yeni mesaj yok.")
            return contact

        previews = [(m["text"] or f"[{m['kind']}]") for m in msgs]
        joined_preview = " ⏎ ".join(previews)
        logger.info(f"[WA] {contact} ({role.value}) | {len(msgs)} mesaj | {joined_preview[:110]}")
        for p in previews:
            self._mirror_to_bridge(f"[WHATSAPP] {contact}: {p[:200]}")

        # --- kara liste (herhangi bir mesajda gecerse tumunu atla) ---
        all_text = " ".join(m["text"] for m in msgs if m["text"])
        if all_text and self._blacklist_rx and self._blacklist_rx.search(all_text):
            logger.warning(f"[WA] kara liste kelimesi - yanit verilmedi: {contact}")
            await self._notify_admin("WhatsApp kara liste", f"{contact}: {joined_preview[:120]}")
            return contact

        # --- yonetici komutu (son metin mesaji uzerinden) ---
        if role is Role.ADMIN:
            for m in reversed(msgs):
                if m["kind"] != "text" or not m["text"]:
                    continue
                admin_reply = await self._try_admin_command(m["text"])
                if admin_reply is not None:
                    await self._plain_send(page, admin_reply)
                    self._mirror_to_bridge(f"[WHATSAPP] (JARVIS->{contact}): {admin_reply[:200]}")
                    return contact
                break

        # --- mod kapisi ---
        if self.mode is Mode.SILENT:
            logger.info(f"[WA] sessiz mod - yanit yok: {contact}")
            return contact
        if self.mode is Mode.MANUAL and role is not Role.ADMIN:
            await self._notify_admin("WhatsApp (manuel mod)", f"{contact}: {joined_preview[:160]}")
            return contact

        # --- cooldown ---
        if role is not Role.ADMIN and not self._cooldown_ok(contact):
            logger.info(f"[WA] cooldown - yanit ertelendi: {contact}")
            return contact

        # --- her mesaji coz (metin / sesli mesaj transkripti / gorsel analizi); sonra tek mesaja birlestirilir ---
        resolved: list[str] = []
        for m in msgs:
            t = await self._resolve_message_text(page, m)
            if t:
                resolved.append(t)
        if not resolved:
            logger.info(f"[WA] islenebilir icerik yok: {contact}")
            return contact

        reply = await self._generate_reply(contact, resolved)
        if not reply:
            logger.warning(f"[WA] yanit uretilemedi: {contact} - 60 sn sonra tekrar denenecek")
            self._retry_after[contact] = time.time() + 60.0
            return contact

        await self._human_send(page, reply)
        self._retry_after.pop(contact, None)
        if (
            self.cfg.notify_personal_questions
            and role is not Role.ADMIN
            and self._is_personal_question(" ".join(resolved))
        ):
            await self._notify_admin(
                "WhatsApp: seni soruyorlar",
                f"{contact}: {' / '.join(resolved)[:160]} -> JARVIS: {reply[:120]}",
            )
        self._memory.add(contact, "user", self._merge_messages(resolved))
        self._memory.add(contact, "assistant", reply)
        self._last_reply_at[contact] = time.time()
        self._mirror_to_bridge(f"[WHATSAPP] (JARVIS->{contact}): {reply[:200]}")
        logger.success(f"[WA] {len(resolved)} mesaj yanitlandi -> {contact}: {reply[:90]}")
        return contact

    # -------------------------------------------------------------- DOM okuma

    async def _chat_identity(self, page: Any) -> str:
        try:
            loc = page.locator(SEL["header_title"]).first
            if await loc.count() == 0:
                return ""
            title = await loc.get_attribute("title")
            return (title or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    async def _is_group(self, page: Any) -> bool:
        try:
            return await page.locator(SEL["group_icon"]).count() > 0
        except Exception:  # noqa: BLE001
            return False

    async def _read_incoming_batch(self, page: Any, *, cap: int = 12) -> list[dict[str, Any]]:
        """Yanitlanmasi gereken GELEN balonlari kronolojik sirayla dondurur.

        Sohbetin sonundan basa dogru gidilir; kendi bir `message-out` balonumuza
        (bot ya da telefondan verilmis cevap) ulasilinca durulur. Aradaki gelen
        mesajlar = henuz yanitlanmamis. Son balon bizden ise liste bos doner.
        `cap` yalnizca guvenlik ust siniridir (art arda cok mesaj).
        """
        out: list[dict[str, Any]] = []
        limit = max(1, cap)
        try:
            bubbles = page.locator(f'{SEL["msg_in"]}, {SEL["msg_out"]}')
            n = await bubbles.count()
            if n == 0:
                return out

            collected: list[Any] = []
            for i in range(n - 1, -1, -1):
                b = bubbles.nth(i)
                try:
                    cls = (await b.get_attribute("class")) or ""
                except Exception:  # noqa: BLE001
                    cls = ""
                if "message-out" in cls:
                    break  # kendi mesajimiza ulastik - oncesi zaten yanitlanmis
                collected.append(b)
                if len(collected) >= limit:
                    break

            for b in reversed(collected):  # kronolojik sira
                parsed = await self._parse_bubble(b)
                if parsed is not None:
                    out.append(parsed)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[WA] gelen mesaj yiginini okunamadi: {exc!r}")
        return out

    async def _parse_bubble(self, bubble: Any) -> dict[str, Any] | None:
        """Tek bir balonu tur (text / voice / image) + metin olarak cozer."""
        try:
            html = (await bubble.inner_html()).lower()

            kind = "text"
            if any(m in html for m in ("audio-play", "ptt-status", "voice message", "sesli mesaj")):
                kind = "voice"
            elif "blob:" in html and "<img" in html:
                kind = "image"

            text = ""
            try:
                txt_loc = bubble.locator(SEL["msg_text"])
                if await txt_loc.count() > 0:
                    text = (await txt_loc.last.inner_text()).strip()
            except Exception:  # noqa: BLE001
                pass
            if not text and kind == "text":
                try:
                    text = (await bubble.inner_text()).strip()
                except Exception:  # noqa: BLE001
                    text = ""

            if kind == "text" and not text:
                return None  # bos metin balonu (sistem satiri vb.)
            return {"kind": kind, "text": text, "bubble": bubble}
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[WA] balon okunamadi: {exc!r}")
            return None

    async def _resolve_message_text(self, page: Any, msg: dict[str, Any]) -> str:
        kind = msg["kind"]
        if kind == "text":
            return msg["text"]

        if not self.cfg.media_enabled:
            logger.info("[WA] medya devre disi - sesli/gorsel mesaj atlaniyor.")
            return ""

        media_path = await self._download_media(page, msg["bubble"], kind)
        if media_path is None:
            await self._notify_admin(
                "WhatsApp medya",
                f"{kind} mesaji indirilemedi - selektor guncellemesi gerekebilir.",
            )
            return ""

        try:
            if self._media.too_big(media_path):
                logger.warning(f"[WA] medya cok buyuk ({self.cfg.media_max_mb} MB siniri).")
                return ""
            if kind == "voice":
                transcript = await transcribe_audio(media_path)
                if not transcript:
                    return ""
                return f'(Sesli mesaj transkripti) {transcript}'
            # image
            caption = msg["text"]
            analysis = await describe_image(media_path, caption=caption)
            if not analysis:
                return ""
            base = f'(Gorsel iceriginin analizi) {analysis}'
            return f'{base}\n(Resim alti yazisi: "{caption}")' if caption else base
        finally:
            self._media.discard(media_path)

    async def _download_media(self, page: Any, bubble: Any, kind: str) -> Path | None:
        default_ext = ".ogg" if kind == "voice" else ".jpg"
        target = self._media.path_for(kind, default_ext)
        try:
            await bubble.scroll_into_view_if_needed(timeout=3_000)
            await bubble.hover(timeout=3_000)
            await page.wait_for_timeout(250)

            async with page.expect_download(timeout=20_000) as dl_info:
                icon = bubble.locator(SEL["download_icon"]).first
                if await icon.count() > 0:
                    await icon.click(timeout=4_000)
                else:
                    ctx = bubble.locator(SEL["msg_context"]).first
                    await ctx.click(timeout=4_000)
                    await page.wait_for_timeout(300)
                    item = page.locator(SEL["menu_download"]).first
                    await item.click(timeout=4_000)

            download = await dl_info.value
            suffix = Path(download.suggested_filename or "").suffix or default_ext
            target = target.with_suffix(suffix)
            await download.save_as(str(target))
            self._media.register(target)
            logger.info(f"[WA] medya indirildi: {target.name} ({target.stat().st_size} B)")
            return target
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[WA] medya indirilemedi ({kind}): {exc!r}")
            return None

    # -------------------------------------------------------------- LLM yanit

    @staticmethod
    def _is_personal_question(text: str) -> bool:
        """Karsi taraf Sezai'nin nerede/ne yapiyor/musait mi oldugunu mu soruyor?"""
        norm = normalize_tr(text)
        if _PERSONAL_RX.search(norm):
            return True
        return any(_PERSONAL_ALONE_RX.match(line) for line in norm.splitlines())

    def _status_context(self) -> str:
        """Ders programindan (okul) GERCEK durum bilgisi; yoksa 'bilinmiyor' der."""
        try:
            from tools.okul_tool import _load, _schedule_for

            data = _load()
            if data:
                now = datetime.now()
                hour = now.hour + now.minute / 60.0
                today = _schedule_for(data, now.weekday())
                for c in today:
                    start, end = int(c["baslangic"][:2]), int(c["bitis"][:2])
                    if start <= hour < end:
                        room = f", derslik {c['derslik']}" if c.get("derslik") else ""
                        return (
                            f"Ders programina gore Sezai su an '{c['ders']}' dersinde "
                            f"({c['baslangic']}-{c['bitis']}{room})."
                        )
                upcoming = [c for c in today if int(c["baslangic"][:2]) > hour]
                if upcoming:
                    n = upcoming[0]
                    return (
                        f"Ders programina gore Sezai'nin bir sonraki dersi {n['baslangic']}'de "
                        f"'{n['ders']}'. Su anki yeri kesin BILINMIYOR."
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[WA] durum bilgisi okunamadi: {exc!r}")
        return "Sezai'nin su anki yeri/durumu BILINMIYOR."

    def _system_instruction(self, personal: bool = False, search: bool | None = None) -> str:
        """Kisilik promptu + durustluk kurallari + tarih/saat (+ arama yonergesi, kisisel soru baglami)."""
        try:
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo("Europe/Istanbul"))
        except Exception:  # noqa: BLE001 - tzdata yoksa yerel saat
            now = datetime.now()
        gunler = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi", "Pazar"]
        parts = [
            self.cfg.system_prompt,
            HONESTY_RULES,
            f"Su an: {now:%d.%m.%Y} {gunler[now.weekday()]}, saat {now:%H:%M} (Turkiye).",
        ]
        use_search = self.cfg.web_search_enabled if search is None else search
        if use_search:
            parts.append(
                "Guncel ya da olgusal bir soru gelirse (skor, hava, fiyat, saat, tarih, haber, "
                "bilgi) Google aramasiyla dogrula ve dogru bilgiyi ver. Arayip bulamazsan "
                "uydurma, 'bakip donerim' de."
            )
        elif search is False:
            parts.append(
                "Internete erisemiyorsun: guncel bilgi (skor, hava, fiyat, haber) gerektiren sorularda "
                "tahmin yurutme, bilmedigini soyle ya da 'bakip donerim' de."
            )
        if personal:
            parts.append(
                "KISISEL DURUM SORUSU: Karsi taraf Sezai'nin nerede oldugunu / ne yaptigini / musait "
                f"olup olmadigini soruyor. {self._status_context()} Yalnizca bu bilgiyi kullan; baska "
                "konum, aktivite, plan ya da saat UYDURMA, soz verme. Bu soruda kendini Sezai adina "
                "yazan asistan olarak konumla ve ucuncu tekil kisiyle konus: kisa, sicak bir cevap ver "
                "ve Sezai'ye ilettigini, musait olunca kendisinin donecegini soyle."
            )
        return "\n\n".join(parts)

    # Bir yanit icin toplam ust sinir (model zinciri + yeniden denemeler dahil)
    REPLY_TIMEOUT_S = 50.0

    @staticmethod
    def _tool_unsupported(exc: BaseException) -> bool:
        """Hata 'arac (google_search) desteklenmiyor' turunden mu? Kota/404/zaman asimi degil."""
        if isinstance(exc, asyncio.TimeoutError):
            return False
        msg = str(exc).upper()
        if any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND", "503", "UNAVAILABLE")):
            return False
        return "TOOL" in msg or "INVALID_ARGUMENT" in msg or "400" in msg

    @staticmethod
    def _search_tool(types: Any) -> Any:
        for factory in (
            lambda: types.Tool(google_search=types.GoogleSearch()),
            lambda: types.Tool(google_search_retrieval=types.GoogleSearchRetrieval()),
        ):
            try:
                return factory()
            except Exception:  # noqa: BLE001
                continue
        return None

    @staticmethod
    def _merge_messages(messages: list[str]) -> str:
        """Art arda gelen mesajlari tek metne birlestirir (her mesaj ayri satirda)."""
        return "\n".join(m.strip() for m in messages if m and m.strip())

    async def _generate_reply(self, contact: str, user_messages: list[str]) -> str:
        """Gelen mesaj(lar)a TEK bir yanit uretir. Art arda gelen mesajlar tek bir
        'user' turunda (satir satir) birlestirilip modele verilir.

        Saglayici sirasi `reply_provider` ayarina gore (OpenRouter -> Gemini yedegi)."""
        if not user_messages:
            return ""
        merged = self._merge_messages(user_messages)
        personal = (
            self._role_for(contact) is not Role.ADMIN and self._is_personal_question(merged)
        )
        history = self._memory.history(contact)

        for provider in self._provider_order():
            try:
                if provider == "openrouter":
                    text = await self._reply_openrouter(personal, history, merged)
                else:
                    text = await self._reply_gemini(personal, history, merged)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[WA] {provider} yanit uretemedi: {exc!r}")
                continue
            text = self._clean_reply(text)
            if text:
                logger.info(f"[WA] yanit saglayicisi: {provider}")
                return text
        logger.error("[WA] yanit uretimi basarisiz (tum saglayicilar).")
        return ""

    @staticmethod
    def _clean_reply(text: str) -> str:
        """Akil yurutme etiketlerini at, tek satira indir (WhatsApp'ta Enter = gonder)."""
        text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I).strip()
        return re.sub(r"\s*\n\s*", " ", text)[:1500].strip()

    # ---------------------------------------------------------- saglayicilar

    # OpenRouter: her model denemesi icin ust sinir (sn)
    OPENROUTER_TIMEOUT_S = 25.0

    @staticmethod
    def _openrouter_key() -> str:
        return (os.getenv("OPENROUTER_API_KEY") or "").strip()

    def _openrouter_models(self) -> list[str]:
        primary = (os.getenv("OPENROUTER_MODEL") or self.cfg.openrouter_model or "").strip()
        chain = [primary, *self.cfg.openrouter_fallback_models]
        seen: set[str] = set()
        return [m.strip() for m in chain if m and m.strip() and not (m in seen or seen.add(m))]

    def _provider_order(self) -> list[str]:
        mode = (self.cfg.reply_provider or "auto").strip().lower()
        or_ready = bool(self._openrouter_key() and self._openrouter_models())
        if mode == "gemini":
            return ["gemini"]
        if mode == "openrouter":
            return ["openrouter"] if or_ready else []
        return ["openrouter", "gemini"] if or_ready else ["gemini"]

    async def _openrouter_chat(self, model: str, messages: list[dict[str, str]]) -> str:
        """Tek bir OpenRouter cagrisi (OpenAI uyumlu API). Bos icerik = basarisiz."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self._openrouter_key(),
            timeout=self.OPENROUTER_TIMEOUT_S,
            max_retries=0,
            default_headers={"HTTP-Referer": "https://localhost/jarvis", "X-Title": "JARVIS WhatsApp"},
        )
        try:
            resp = await client.chat.completions.create(
                model=model, messages=messages, temperature=0.7, max_tokens=600
            )
        finally:
            with contextlib.suppress(Exception):
                await client.close()
        return ((resp.choices[0].message.content if resp.choices else "") or "").strip()

    @staticmethod
    def _system_unsupported(exc: BaseException) -> bool:
        """Bazi ucretsiz modeller 'system' rolunu kabul etmez (400 ... instruction ...)."""
        msg = str(exc).upper()
        return "400" in msg and ("INSTRUCTION" in msg or ("SYSTEM" in msg and "SUPPORT" in msg))

    @staticmethod
    def _fold_system(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """System talimatini ilk kullanici mesajinin basina katar."""
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [dict(m) for m in messages if m["role"] != "system"]
        if not system:
            return rest
        if rest and rest[0]["role"] == "user":
            rest[0]["content"] = f"[TALIMAT]\n{system}\n\n[MESAJ]\n{rest[0]['content']}"
        else:
            rest.insert(0, {"role": "user", "content": f"[TALIMAT]\n{system}"})
        return rest

    async def _reply_openrouter(self, personal: bool, history: list[dict[str, str]], merged: str) -> str:
        models = self._openrouter_models()
        if not (self._openrouter_key() and models):
            raise RuntimeError("OpenRouter anahtari/modeli yok")
        # Arama araci yok: 'uydurma, bilmiyorsan bakip donerim de' yonergesi kalir
        system = self._system_instruction(personal, search=False)
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for turn in history:
            messages.append(
                {"role": "assistant" if turn["role"] == "assistant" else "user", "content": turn["text"]}
            )
        messages.append({"role": "user", "content": merged})

        last: BaseException | None = None
        for model in models:
            for folded in (False, True):
                payload = self._fold_system(messages) if folded else messages
                try:
                    text = await asyncio.wait_for(
                        self._openrouter_chat(model, payload), timeout=self.OPENROUTER_TIMEOUT_S + 5
                    )
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    if not folded and self._system_unsupported(exc):
                        logger.info(f"[WA] {model} system rolunu desteklemiyor; talimat mesaja katiliyor")
                        continue
                    logger.warning(f"[WA] OpenRouter {model}: {exc!r}")
                    break
                if text:
                    return text
                last = RuntimeError(f"{model}: bos yanit")
                logger.warning(f"[WA] OpenRouter {model}: bos yanit, siradaki model")
                break
        raise last or RuntimeError("OpenRouter yanit vermedi")

    async def _reply_gemini(self, personal: bool, history: list[dict[str, str]], merged: str) -> str:
        from agents.genai_util import generate_with_retry
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self.settings.gemini_api_key,
            http_options=types.HttpOptions(
                api_version=self.settings.agents_api_version, timeout=90_000
            ),
        )
        contents: list[Any] = [
            types.Content(
                role="model" if turn["role"] == "assistant" else "user",
                parts=[types.Part(text=turn["text"])],
            )
            for turn in history
        ]
        contents.append(types.Content(role="user", parts=[types.Part(text=merged)]))

        system = self._system_instruction(personal)
        search_tool = self._search_tool(types) if self.cfg.web_search_enabled else None

        async def _ask(tools: list[Any] | None) -> Any:
            # Tek sohbet tum yoklama dongusunu dakikalarca tikamasin: toplam sure sinirli
            return await asyncio.wait_for(
                generate_with_retry(
                    client,
                    model=self.settings.agent_model_chain,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0.7,
                        max_output_tokens=600,
                        **({"tools": tools} if tools else {}),
                    ),
                    attempts=2,
                ),
                timeout=self.REPLY_TIMEOUT_S,
            )

        try:
            resp = await _ask([search_tool] if search_tool else None)
        except Exception as exc:  # noqa: BLE001
            if not (search_tool and self._tool_unsupported(exc)):
                raise   # kota / zaman asimi / ag hatasi: aramasiz tekrar denemek isi yavaslatir
            logger.warning(f"[WA] model arama aracini desteklemiyor ({exc!r}); aramasiz deneniyor")
            resp = await _ask(None)
        return (getattr(resp, "text", None) or "").strip()

    # -------------------------------------------------------------- gonderim

    PROACTIVE_TIMEOUT_S = 120.0

    async def send_proactive_message(self, chat_id: str, text: str) -> bool:
        """Disaridan (zamanlayici, bildirim dagiticisi) proaktif mesaj gonderir.

        `chat_id` telefon numarasidir (orn. "905551112233"). Mesaj kuyruga alinir ve
        yoklama dongusu tarafindan sayfa uzerinden gonderilir; bu yuzden baska bir
        thread / event loop'tan cagrilmasi guvenlidir. Gonderildiyse True; kol kapali,
        bagli degil ya da zaman asimi -> False.
        """
        text = (text or "").strip()
        if not (self.cfg.enabled and text and re.sub(r"\D", "", chat_id or "")):
            return False
        loop, queue = self._loop, self._outgoing
        if loop is None or queue is None or loop.is_closed():
            logger.info("[WA] proaktif mesaj atlandi: WhatsApp kolu calismiyor.")
            return False

        async def _enqueue_and_wait() -> bool:
            fut: asyncio.Future[bool] = loop.create_future()
            queue.put_nowait((chat_id, text, fut))
            try:
                return await asyncio.wait_for(asyncio.shield(fut), self.PROACTIVE_TIMEOUT_S)
            except asyncio.TimeoutError:
                fut.cancel()  # kuyrukta bekliyorsa gonderilmesin
                logger.warning("[WA] proaktif mesaj zaman asimi (oturum bagli degil?)")
                return False

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            return await _enqueue_and_wait()
        cfut = asyncio.run_coroutine_threadsafe(_enqueue_and_wait(), loop)
        return await asyncio.wrap_future(cfut)

    async def _drain_outgoing(self, page: Any) -> None:
        """Kuyruktaki proaktif mesajlari gonderir (yalnizca yoklama dongusunden)."""
        queue = self._outgoing
        while queue is not None and not queue.empty():
            target, text, fut = queue.get_nowait()
            if fut.done():  # zaman asimina ugramis / iptal
                continue
            ok = False
            try:
                ok = await self._send_to_number(page, target, text)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[WA] proaktif gonderim hatasi: {exc!r}")
            if not fut.done():
                fut.set_result(ok)

    async def _send_to_number(self, page: Any, number: str, text: str) -> bool:
        digits = re.sub(r"\D", "", number)
        await page.goto(f"{WA_URL}/send?phone={digits}", wait_until="domcontentloaded")
        try:
            await page.locator(SEL["input_box"]).last.wait_for(timeout=30_000)
        except Exception:  # noqa: BLE001
            logger.warning(f"[WA] {digits} icin sohbet acilamadi (numara WhatsApp'ta yok?)")
            return False
        await self._plain_send(page, text)
        self._mirror_to_bridge(f"[WHATSAPP] (JARVIS->{digits}): {text[:200]}")
        logger.info(f"[WA] proaktif mesaj gonderildi -> {digits}")
        return True

    async def _human_send(self, page: Any, text: str) -> None:
        """Insan simulasyonu: dusunme gecikmesi + 'yaziyor...' + kademeli yazim."""
        box = await self._focus_input(page)
        if box is None:
            logger.warning("[WA] yazma kutusu bulunamadi.")
            return

        await self._think_pause(len(text))

        try:
            if len(text) <= 180:
                await box.press_sequentially(text, delay=self._rand(28, 65))
            else:
                # uzun metin: bir kismini yaz (typing gorunur), sonra geri kalanini yapistir
                head = text[:60]
                await box.press_sequentially(head, delay=self._rand(28, 55))
                await box.press_sequentially(text[60:], delay=0)
            await page.wait_for_timeout(self._rand(200, 500))
            await self._click_send(page, box)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[WA] gonderim hatasi: {exc!r}")

    async def _plain_send(self, page: Any, text: str) -> None:
        """Yonetici komut yanitlari - simulasyonsuz, hizli."""
        box = await self._focus_input(page)
        if box is None:
            return
        try:
            await box.fill(text[:3000])
            await page.wait_for_timeout(120)
            await self._click_send(page, box)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[WA] komut yaniti gonderilemedi: {exc!r}")

    async def _focus_input(self, page: Any) -> Any:
        try:
            box = page.locator(SEL["input_box"]).last
            if await box.count() == 0:
                return None
            await box.click(timeout=4_000)
            return box
        except Exception:  # noqa: BLE001
            return None

    async def _click_send(self, page: Any, box: Any) -> None:
        btn = page.locator(SEL["send_btn"]).last
        try:
            if await btn.count() > 0:
                await btn.click(timeout=3_000)
                return
        except Exception:  # noqa: BLE001
            pass
        await box.press("Enter")

    async def _think_pause(self, text_len: int) -> None:
        if not self.cfg.typing_delay_enabled:
            return
        lo, hi = self.cfg.typing_min_seconds, self.cfg.typing_max_seconds
        secs = min(hi, max(lo, text_len / 22.0))
        secs *= self._rand(80, 120) / 100.0
        await asyncio.sleep(secs)

    @staticmethod
    def _rand(lo: int, hi: int) -> int:
        import random

        return random.randint(lo, hi)

    # -------------------------------------------------------------- yonetici komutlari

    async def _try_admin_command(self, text: str) -> str | None:
        """Metin bir JARVIS komutu ise yanit string'i, degilse None doner."""
        raw = text.strip()
        low = raw.lower()
        # "cyraen" kisa sureli eski ad: alistirilmis yazim da komut sayilir
        if not _ADMIN_PREFIX_RE.match(low):
            return None
        body = _ADMIN_PREFIX_RE.sub("", raw).strip()
        bl = body.lower()

        if not body or bl in ("yardim", "yardım", "help", "?"):
            return self._help_text()

        if bl in ("durum", "status"):
            return self._status_text()

        m = re.match(r"mod[ua]?\s+(otomatik|manuel|sessiz|auto|manual|silent)", bl)
        if m or bl in ("sessiz", "otomatik", "manuel"):
            token = (m.group(1) if m else bl)
            mapping = {
                "auto": Mode.AUTO, "otomatik": Mode.AUTO,
                "manual": Mode.MANUAL, "manuel": Mode.MANUAL,
                "silent": Mode.SILENT, "sessiz": Mode.SILENT,
            }
            self.mode = mapping.get(token, self.mode)
            logger.info(f"[WA] mod degisti -> {self.mode.value}")
            return f"✅ Mod: {self.mode.value}"

        if re.match(r"(mikrofon|mik)\s+(kapat|sustur|kapa)", bl):
            return self._engine_call("set_mic_muted", True, ok="🔇 Mikrofon susturuldu.")
        if re.match(r"(mikrofon|mik)\s+(ac|aç|ac)", bl):
            return self._engine_call("set_mic_muted", False, ok="🎙️ Mikrofon acildi.")
        if re.match(r"(hoparlor|hoparlör|ses)\s+(kapat|sustur)", bl):
            return self._engine_call("set_output_muted", True, ok="🔇 PC hoparloru susturuldu.")
        if re.match(r"(hoparlor|hoparlör|ses)\s+(ac|aç)", bl):
            return self._engine_call("set_output_muted", False, ok="🔊 PC hoparloru acildi.")

        if bl in ("hafiza sil", "hafıza sil", "gecmisi temizle", "geçmişi temizle"):
            self._memory.clear()
            return "🧹 Tum WhatsApp sohbet hafizasi temizlendi."

        m = re.match(r"(soyle|söyle|de ki|ilet)[:\s]+(.+)", body, flags=re.IGNORECASE)
        if m:
            payload = m.group(2).strip()
            self._mirror_to_bridge(f"[WHATSAPP] {payload}")
            return f"📨 Beyne iletildi: {payload[:120]}"

        m = re.match(r"(ajan|gorev|görev)[:\s]+(.+)", body, flags=re.IGNORECASE)
        if m:
            return self._queue_agent_task(m.group(2).strip())

        if bl in ("kapan", "kapat", "beyni kapat", "cikis", "çıkış"):
            logger.warning("[WA] admin uzaktan kapatma komutu verdi.")
            self._safe_engine("request_shutdown")
            self.request_shutdown()
            return "🛑 JARVIS kapatiliyor."

        return f"❓ Anlamadim. '{self._help_text_short()}'"

    def _engine_call(self, method: str, *args: Any, ok: str) -> str:
        if self.engine is None:
            return "⚠️ Beyin motoru bagli degil (yalnizca WhatsApp modu)."
        try:
            getattr(self.engine, method)(*args)
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[WA] engine.{method} hatasi: {exc!r}")
            return f"⚠️ Komut calistirilamadi: {exc}"

    def _safe_engine(self, method: str, *args: Any) -> None:
        if self.engine is None:
            return
        try:
            getattr(self.engine, method)(*args)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[WA] engine.{method} hatasi: {exc!r}")

    def _queue_agent_task(self, task: str) -> str:
        if not task:
            return "⚠️ Gorev metni bos."
        try:
            path = self.settings.agent_inbox_path
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"id": f"wa-{int(time.time())}", "task": task, "agent": "auto",
                 "context": "WhatsApp uzerinden admin tarafindan gonderildi"},
                ensure_ascii=False,
            )
            with path.open("a", encoding="utf-8") as fh:
                fh.write(payload + "\n")
            return f"🧠 Ajan kuyruguna eklendi: {task[:120]}"
        except OSError as exc:
            return f"⚠️ Gorev yazilamadi: {exc}"

    def _status_text(self) -> str:
        lines = [
            "🤖 *JARVIS · WhatsApp*",
            f"Mod: {self.mode.value}",
            f"Calisma suresi: {int(time.time() - self._started_at)} sn",
            f"Aktif sohbet hafizasi: {self._memory.contacts} kisi",
            f"Admin: {len(self.cfg.admin_numbers)} · Whitelist modu: {self.cfg.whitelist_mode}",
        ]
        if self.engine is not None:
            try:
                lines.append(
                    "Beyin: " + ("bagli" if getattr(self.engine, "session", None) else "bagli degil")
                )
                lines.append("Mikrofon: " + ("kapali" if self.engine.mic_muted else "acik"))
                lines.append("Hoparlor: " + ("kapali" if self.engine.output_muted else "acik"))
            except Exception:  # noqa: BLE001
                pass
        else:
            lines.append("Beyin motoru: bagli degil")
        return "\n".join(lines)

    @staticmethod
    def _help_text() -> str:
        return (
            "🤖 *JARVIS komutlari*\n"
            "• JARVIS durum\n"
            "• JARVIS modu [otomatik|manuel|sessiz]\n"
            "• JARVIS sessiz\n"
            "• JARVIS mikrofon [aç|kapat]\n"
            "• JARVIS hoparlör [aç|kapat]\n"
            "• JARVIS söyle: <metin>   (canli beyne ilet)\n"
            "• JARVIS ajan: <görev>    (ajan kuyruguna ekle)\n"
            "• JARVIS hafıza sil\n"
            "• JARVIS kapat            (tumunu durdur)"
        )

    @staticmethod
    def _help_text_short() -> str:
        return "JARVIS durum | modu ... | mikrofon aç/kapat | söyle: ... | kapat"

    # -------------------------------------------------------------- yardimcilar

    def _role_for(self, contact: str) -> Role:
        if self._match(contact, self.cfg.admin_numbers):
            return Role.ADMIN
        mode = (self.cfg.whitelist_mode or "list").lower()
        if mode == "all":
            return Role.WHITELIST
        if mode == "off":
            return Role.OTHER
        if self._match(contact, self.cfg.allowed_contacts):
            return Role.WHITELIST
        return Role.OTHER

    @staticmethod
    def _match(contact: str, entries: list[str]) -> bool:
        if not contact or not entries:
            return False
        c_low = contact.lower().strip()
        c_digits = re.sub(r"\D", "", contact)
        for entry in entries:
            e = (entry or "").strip()
            if not e:
                continue
            if e.lower() == c_low:
                return True
            e_digits = re.sub(r"\D", "", e)
            if e_digits and c_digits:
                if e_digits == c_digits:
                    return True
                tail = e_digits[-10:]
                if len(tail) >= 9 and c_digits.endswith(tail):
                    return True
            elif not e_digits and e.lower() in c_low:
                return True
        return False

    def _cooldown_ok(self, contact: str) -> bool:
        last = self._last_reply_at.get(contact, 0.0)
        return (time.time() - last) >= self.cfg.cooldown_seconds

    @staticmethod
    def _compile_blacklist(words: list[str]) -> re.Pattern[str] | None:
        clean = [re.escape(w.strip()) for w in words if w and w.strip()]
        if not clean:
            return None
        return re.compile(r"(?<!\w)(?:" + "|".join(clean) + r")(?!\w)", re.IGNORECASE)

    def _mirror_to_bridge(self, line: str) -> None:
        from core.bridge_mirror import mirror_to_bridge

        mirror_to_bridge(line, self._bridge_path)

    async def _notify_admin(self, title: str, message: str) -> None:
        if self._notifier is None:
            logger.info(f"[WA][bildirim] {title} - {message}")
            return
        try:
            await self._notifier.notify(f"JARVIS · {title}", message, priority=4, tags=["speech_balloon"])
        except Exception:  # noqa: BLE001
            logger.debug("[WA] admin bildirimi gonderilemedi")


def load_whatsapp_config(settings: Settings | None = None) -> WhatsAppConfig:
    """main.py icin kisayol."""
    return WhatsAppConfig.load(settings)
