"""Merkezi konfigurasyon.

Tum ayarlar burada toplanir; ortam degiskenleri (.env) ile override edilebilir.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from config.legacy_env import alias_legacy_env
from config.secrets import get_secret

BASE_DIR = Path(__file__).resolve().parent.parent

# PyInstaller ile paketlendiginde:
#   RESOURCE_DIR -> salt-okunur gomulu dosyalar (prompts/, assets/)
#   APP_DIR      -> exe'nin yani (yazilabilir: .env, data/, bridge/, loglar)
if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    APP_DIR = Path(sys.executable).parent
else:
    RESOURCE_DIR = BASE_DIR
    APP_DIR = BASE_DIR

ASSETS_DIR = RESOURCE_DIR / "assets"

for _candidate in (APP_DIR / ".env", BASE_DIR / ".env"):
    if _candidate.is_file():
        load_dotenv(_candidate)
        break
alias_legacy_env()  # eski .env'deki JARVIS_* -> CYRAEN_*

_FALLBACK_PROMPT = "Sen CYRAEN (okunusu Siren) adinda, Turkce konusan gelismis bir yapay zeka asistanisin."

_WAKE_PHRASES = {"hey_jarvis": "Hey Jarvis", "hey_siren": "Hey Siren", "hey_cyraen": "Hey Siren"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "evet"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class AudioConfig(BaseModel):
    """PyAudio akis parametreleri."""

    channels: int = 1
    sample_width: int = 2  # paInt16 => 2 byte
    send_sample_rate: int = 16_000  # mikrofon -> model
    receive_sample_rate: int = 24_000  # model -> hoparlor
    chunk_size: int = 1_024


class Settings(BaseModel):
    """Uygulamanin tum ayarlari."""

    gemini_api_key: str = Field(..., description="Google AI Studio API anahtari")

    model: str = "models/gemini-2.5-flash-native-audio-latest"
    api_version: str = "v1alpha"
    voice_name: str = "Puck"
    language_code: str = "tr-TR"
    # Kisilik modlari (core/personas.py): HUD'daki EKIPLER kartindan secilir.
    friday_voice: str = "Kore"
    ultron_voice: str = "Charon"
    ultron_fx: bool = True  # ULTRON sesine robotik/metalik efekt (core/voice_fx.py)

    system_prompt_path: Path = RESOURCE_DIR / "prompts" / "system_prompt.txt"
    persona_prompt_dir: Path = RESOURCE_DIR / "prompts" / "personas"
    football_prompt_path: Path = RESOURCE_DIR / "prompts" / "football_analyst.md"
    data_dir: Path = APP_DIR / "data"
    log_file: Path = APP_DIR / "data" / "brain.log"
    log_level: str = "INFO"

    # Harici ajan koprusu: bu dosyaya yazilan her satir canli oturuma enjekte edilir.
    bridge_outbox_path: Path = APP_DIR / "bridge" / "outbox.txt"
    bridge_poll_interval: float = 0.5

    # Masaustu / pencere davranisi
    always_on_top: bool = True
    minimize_to_tray: bool = True
    # Arayuz: "hud" = Komuta HUD (kartlar + radyal graf), "classic" = eski panel yerlesimi
    ui_style: str = "hud"
    hud_weather_location: str = "İzmir"
    # Acilis animasyonu: "orb" = Zoey OS orb'u ortaya suzulerek gelir (ui/hud/orb_view.py),
    # "3d" = 3B zirh (ui/hud/boot3d.py, web3d/), "classic" = halka animasyonu.
    # Sayfa derlenmemisse ya da QtWebEngine yoksa kendiliginden "classic" oynar.
    boot_style: str = "orb"
    # 3B acilis bittikten sonra zirh kac saniye ekranda kalsin (0 = Esc / "ARAYÜZE GEÇ" bekler)
    boot_hold_s: float = 3.0
    # Icerik paneli (tools/panel_tools.py): belge aranan/acilan klasorler, `;` ile ayrilir.
    # Bos = Belgeler + Masaustu + Indirilenler.
    docs_dirs: str = ""

    # Acilista alkis sesi cal
    startup_sound: bool = True
    startup_sound_path: Path = ASSETS_DIR / "applause.wav"

    webcam_enabled: bool = False   # ilk acilista kamera KAPALI - kullanici arayuzden acar
    webcam_index: int = 0
    webcam_interval: float = 1.5
    webcam_jpeg_quality: int = 70

    # Ekran gorusu (screen vision)
    screen_enabled: bool = True
    screen_monitor: int = 1        # mss: 1 = birincil ekran
    screen_interval: float = 1.2   # daha guncel kareler -> daha isabetli tiklama
    screen_jpeg_quality: int = 55

    # Uyandirma kelimesi ("Hey CYRAEN", cevrimdisi openWakeWord). Acikken mikrofon sesi
    # yalnizca uyandiktan sonra wake_window_s boyunca (konustukca uzar) modele gider.
    wake_word_enabled: bool = False
    wake_word_model: str = "hey_jarvis"
    wake_word_threshold: float = 0.5
    wake_window_s: float = 8.0
    # Tek bir "Hey CYRAEN" ile en fazla bu kadar uyanik kalinir (0 = sinirsiz); arka plandaki
    # sohbet pencereyi suresiz acik tutamasin.
    wake_max_awake_s: float = 90.0
    # Kopru mesaji (telefon / ajan / hatirlatici) yanitlanana kadar mikrofon modele en fazla
    # bu kadar kapali kalir; ortam sesi yaniti bolemesin. 0 = kapali.
    bridge_hold_s: float = 45.0
    # Gemini Live "proactive audio": model kendisine hitap edilmeyen konusmaya yanit vermeyebilir.
    proactive_audio: bool = True
    # Temiz acilan oturuma tarih/saat + dunun ozeti + bugunku son konusmalar verilir
    # (core/session_context.py). Kopan oturum zaten kaldigi yerden devam ettirilir.
    session_context_enabled: bool = True

    # Konusmaci dogrulama (core/speaker_verify.py): uyandirma kapisi yalniz kayitli sese acilir.
    # Profil yoksa (scripts/voice_enroll.py calistirilmadiysa) pasiftir.
    speaker_verify_enabled: bool = True
    speaker_threshold: float = 0.0  # 0 = profildeki onerilen esik
    speaker_model_path: Path = APP_DIR / "data" / "voice" / "wespeaker_en_voxceleb_resnet34.onnx"
    speaker_profile_path: Path = APP_DIR / "data" / "voice" / "profile.npz"

    # Cevrimdisi sesli konusma (core/offline_voice.py): internet yokken vosk + yerel model + yerel TTS
    offline_voice_enabled: bool = True
    offline_stt_model: str = ""   # vosk model klasoru; bossa ~/.cache/vosk'taki Turkce model
    offline_tts: str = "auto"     # auto | piper | sapi
    offline_tts_voice: Path = APP_DIR / "data" / "piper" / "tr_TR-dfki-medium.onnx"

    # Uygulama acarken: True => Windows arama cubuguna harf harf yazip Enter'la
    #                   False => dogrudan baslat (kisayol / ShellExecute)
    open_apps_via_search: bool = True
    search_type_delay: float = 0.08  # saniye/karakter (arama cubugu)

    # Web sitesi acarken tarayici adres cubuguna harf harf yaz (adim adim gorunur)
    type_in_browser: bool = True
    browser_type_delay: float = 0.07  # saniye/karakter (tarayici)
    browser_open_delay: float = 2.4   # tarayici acilis bekleme suresi

    # Bir uygulamayi/sekmeyi kapatmadan once kullanici onayi iste
    confirm_before_close: bool = True

    # --- Cok-ajanli sistem (orkestrator) ---
    agents_enabled: bool = True
    agents_model: str = "gemini-flash-lite-latest"
    # Kota dolunca / model kalkinca sirayla denenecek yedekler
    agents_model_fallbacks: list[str] = Field(
        default_factory=lambda: [
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.6-flash",  # gemini-2.5-* yeni anahtarlara kapali (404)
        ]
    )
    agents_api_version: str = "v1beta"
    # Yerel model yedegi (Ollama): bulut zinciri tamamen dusunce son care (core/local_llm.py)
    local_llm_enabled: bool = True
    local_llm_url: str = "http://127.0.0.1:11434"
    local_llm_model: str = "qwen2.5:7b"
    local_llm_small_model: str = "qwen2.5:1.5b"  # buyuk model yuklenemezse
    local_llm_num_ctx: int = 8192  # Ollama varsayilani (2048) aracli prompt'lari keser
    local_llm_timeout: float = 120.0  # ilk yukleme yavas olabilir
    local_llm_keep_alive: str = "10m"
    # OpenRouter (agents.json'da "saglayici/model" bicimli modeller icin; bossa Gemini'ye dusulur)
    openrouter_api_key: str = ""
    # Claude (agents.json'da "claude-*" modeller icin; bossa OpenRouter/Gemini'ye dusulur)
    anthropic_api_key: str = ""
    # Workspace'e bagli olmayan anahtarlar icin zorunlu (Console > Settings > Workspaces)
    anthropic_workspace_id: str = ""
    agent_inbox_path: Path = APP_DIR / "bridge" / "inbox.txt"
    agent_outbox_path: Path = APP_DIR / "bridge" / "outbox.txt"
    agent_config_path: Path = RESOURCE_DIR / "agents" / "agents.json"
    agents_max_concurrent: int = 3
    agent_max_steps: int = 6

    # Otonomi: human_assisted ajanlar calismadan once onay ister mi?
    agents_require_approval: bool = True
    # human_assisted onayi otomatik gec (UI onayi baglanana kadar pratik varsayilan)
    agents_auto_approve_assisted: bool = True

    # Entegrasyonlar (anahtar yoksa yerel dosyaya yazar)
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_table: str = "task_logs"
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"

    # E-posta (IMAP okuma + SMTP gonderme) - Gmail icin uygulama sifresi
    email_address: str = ""
    email_app_password: str = ""
    email_imap_host: str = ""
    email_smtp_host: str = ""
    email_smtp_port: int = 0
    email_sender_name: str = "CYRAEN"

    # Gmail API (OAuth 2.0) - credentials+token varsa IMAP/SMTP yerine kullanilir
    gmail_credentials_file: Path = APP_DIR / "config" / "gmail_credentials.json"
    gmail_token_file: Path = APP_DIR / "data" / "gmail_token.json"

    # Spotify Web API (tools/spotify_tool.py) - oynatma kontrolu Premium ister
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:8888/callback"
    spotify_token_file: Path = APP_DIR / "data" / "spotify_token.json"
    spotify_default_device: str = ""   # bos = aktif cihaz, yoksa ilk PC

    # MCP istemcisi (tools/mcp_hub.py) - Claude Desktop bicimli sunucu listesi
    mcp_enabled: bool = True
    mcp_config_file: Path = APP_DIR / "config" / "mcp_servers.json"

    # Tarayici ajani (tools/browser_tool.py) - WhatsApp'tan ayri kalici profil
    browser_profile_dir: Path = APP_DIR / "data" / "browser_profile"
    browser_headless: bool = False
    browser_blocked_domains: list[str] = Field(default_factory=list)

    # Telegram botu (araclar + otomatik yanit kolu)
    telegram_bot_token: str = ""
    telegram_default_chat_id: str = ""
    # otomatik yanit YALNIZCA bu sohbetlere (bos ise varsayilan sohbet)
    telegram_allowed_chat_ids: list[str] = Field(default_factory=list)
    telegram_auto_reply: bool = True

    # Ulasim (Izmir acik veri). Canli otobus servisleri Bearer token ister.
    izmir_openapi_token: str = ""
    izmirim_kart_no: str = ""
    email_require_confirm: bool = True   # gondermeden once onay iste

    # --- Yerel web konsolu (telefon <-> PC) ---
    web_console_enabled: bool = True
    web_console_port: int = 8770
    web_console_bind: str = "0.0.0.0"       # LAN erisimi; 127.0.0.1 = sadece bu PC
    web_console_token: str = ""             # bos ise sadece localhost'a izin verilir
    # /ekip sayfasi: Stark Ekibi yanitlari edge-tts ile seslendirilir (kapaliysa tarayici sesi)
    team_tts_enabled: bool = True

    # --- El Kontrolu + Kitaplik (/el) ---
    user_name: str = "Sezai"                 # yuz HUD etiketi ("SEZAI · TANINDI")
    vision_model: str = "gemini-3.5-flash"   # raf/kitap okuma modeli (lite yazida zayif); sonra ajan zinciri
    welcome_voice: str = "tr-TR-AhmetNeural"  # yuz kilidi karsilama sesi (edge-tts)
    welcome_text: str = "Yüz tanındı. Hoş geldiniz efendim, tam yetki verildi."

    # --- Uzaktan ses (server modu): motor "network", mikrofon/hoparlor baska bir
    # makinede (run_server.py + remote_client). "local" = bugunku PyAudio davranisi.
    audio_mode: str = "local"               # "local" | "network"
    remote_audio_port: int = 8771
    remote_audio_token: str = ""            # bos ise sadece localhost'a izin verilir
    # run_ui: telefon uygulamasi 8771'e baglaninca konusma telefona gecer (token bossa web token'i)
    phone_audio_enabled: bool = True
    # telefondan PC ekranini izleme + fare/klavye (web/remote_desktop.py); bilincli olarak varsayilan kapali
    remote_desktop_enabled: bool = False
    # modele HIC verilmeyen arac gruplari (tools/tool_declarations.py::TOOL_GROUPS), orn. ["adb", "mcp_browser"]
    tool_groups_disabled: list[str] = Field(default_factory=list)
    remote_confirm_timeout: float = 120.0   # web onayi bu surede gelmezse REDDEDILIR

    # --- Proaktif (hatirlatici + rutinler) ---
    scheduler_enabled: bool = True
    scheduler_tick: float = 15.0
    # SchedulerHandler cron gorevleri. Bos / "kapali" -> sabah ozeti devre disi.
    morning_briefing_time: str = "08:30"
    # sabah ozetinin gidecegi kanallar (voice, telegram, whatsapp, ntfy); bos = hepsi
    morning_briefing_channels: list[str] = Field(default_factory=list)
    health_check_interval_min: int = 60  # 0 -> sistem saglik kontrolu kapali
    health_cpu_alert: float = 90.0       # yuzde esikleri; asilirsa kanallara uyari
    health_mem_alert: float = 90.0
    health_disk_alert: float = 90.0
    # Gun sonu ozeti (core/daily_summary.py): konusma + not + gorevlerden Obsidian'a gunluk.
    # "kapali" = yok. PC o saatte kapaliysa ertesi acilista telafi edilir.
    daily_summary_time: str = "23:30"
    # Haftalik disk bakim raporu (Pazar 20:00): temizlenebilir alan ozeti, hicbir sey silmez
    maintenance_report_weekly: bool = True

    # --- Kod calistirma (varsayilan KAPALI - .env'de acilir) ---
    code_exec_enabled: bool = False
    code_exec_timeout: float = 30.0

    # --- Android ADB kontrol (Ultron modulu) ---
    adb_enabled: bool = True
    adb_path: str = "adb"  # PATH'te degilse platform-tools\adb.exe tam yolu
    adb_tcp_port: int = 5555  # kablosuz ADB varsayilan portu
    # Acilista otomatik `adb connect` denenecek ag adresleri (WiFi cihazlar).
    # env: CYRAEN_ADB_TCP_DEVICES="192.168.1.42,192.168.1.43:5555"
    adb_tcp_devices: list[str] = Field(default_factory=list)
    # Telefon ekran kilidi PIN'i - tanimliysa `unlock_device` kilit ekranini
    # kaydirdiktan sonra PIN'i otomatik girer. env: CYRAEN_ADB_UNLOCK_PIN
    # (GIZLI - .env gitignore'da; loga yazilmaz)
    adb_unlock_pin: str = ""

    # --- GBrain kalici bilgi tabani ---
    gbrain_enabled: bool = True
    gbrain_embed_model: str = "gemini-embedding-001"

    # --- okul (BOTE Ders Merkezi) kopru entegrasyonu ---
    # okul web uygulamasi web konsoluna (/api/okul/push) tam durumunu gonderir;
    # CYRAEN okur ve /api/okul/pull uzerinden degisiklik geri iletir.
    okul_enabled: bool = True
    okul_state_path: Path = APP_DIR / "data" / "okul_state.json"
    okul_outbox_path: Path = APP_DIR / "data" / "okul_outbox.json"

    # --- Obsidian vault entegrasyonu ---
    # Tanimliysa notlar + GBrain kayitlari + konusma kaydi vault'a markdown yazilir.
    obsidian_vault: str = ""
    # Vault icinde alt klasor. Bos ("") ise dogrudan vault kokune yazar
    # (CYRAEN'e ayrilmis kasa icin). Varsayilan "CYRAEN" (paylasilan kasa icin).
    obsidian_subdir: str = "CYRAEN"
    # Konusmalari (her tur: Sen / CYRAEN) otomatik vault'a kaydet
    obsidian_log_conversations: bool = True

    # Yeniden baglanma (exponential backoff)
    reconnect_base_delay: float = 2.0
    reconnect_max_delay: float = 30.0
    reconnect_max_attempts: int = 0  # 0 => sinirsiz

    audio: AudioConfig = Field(default_factory=AudioConfig)

    @field_validator("gemini_api_key")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError(
                "GEMINI_API_KEY tanimli degil. cyraen-brain/.env dosyasini olusturun "
                "(.env.example sablonuna bakin)."
            )
        return value.strip()

    def load_system_prompt(self, persona: str = "cyraen") -> str:
        try:
            text = self.system_prompt_path.read_text(encoding="utf-8").strip()
            text = text or _FALLBACK_PROMPT
        except FileNotFoundError:
            text = _FALLBACK_PROMPT

        # kimlik + KARAKTER kisilige gore degisir; YETENEKLER herkes icin ortak
        identity = ""
        for key in dict.fromkeys((persona or "cyraen", "cyraen")):
            try:
                identity = (self.persona_prompt_dir / f"{key}.md").read_text(
                    encoding="utf-8"
                ).strip()
            except FileNotFoundError:
                continue
            if identity:
                break
        if identity:
            text = f"{identity}\n\n{text}"

        try:
            football = self.football_prompt_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            football = ""
        if football:
            text = f"{text}\n\n{football}"

        return text

    @property
    def wake_phrase(self) -> str:
        """Uyandirma modelinin gercekten tanidigi ifade (ekrandaki ipuclari icin).

        Hazir openWakeWord modellerinde "Hey Siren" yok; ozel model (orn. hey_siren.onnx)
        egitilip CYRAEN_WAKE_WORD_MODEL ile verilene kadar "hey_jarvis" kullanilir.
        """
        stem = Path(self.wake_word_model or "hey_jarvis").stem
        return _WAKE_PHRASES.get(stem, stem.replace("_", " ").title())

    @property
    def agent_model_chain(self) -> list[str]:
        """Birincil model + benzersiz yedekler."""
        chain = [self.agents_model, *self.agents_model_fallbacks]
        seen: set[str] = set()
        return [m for m in chain if m and not (m in seen or seen.add(m))]

    @property
    def vision_model_chain(self) -> list[str]:
        """Raf taramasi icin model zinciri: CYRAEN_VISION_MODEL once, sonra ajan zinciri."""
        chain = [self.vision_model, *self.agent_model_chain]
        seen: set[str] = set()
        return [m for m in chain if m and not (m in seen or seen.add(m))]

    @property
    def obsidian_dir(self) -> Path | None:
        """CYRAEN'in yazacagi vault klasoru; vault tanimsiz/yoksa None.

        `obsidian_subdir` bos ise dogrudan vault koku, degilse `<vault>/<subdir>`.
        """
        raw = (self.obsidian_vault or "").strip()
        if not raw:
            return None
        root = Path(raw).expanduser()
        if not root.is_dir():
            return None
        sub = (self.obsidian_subdir or "").strip().strip("/\\")
        return (root / sub) if sub else root

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.bridge_outbox_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        model=os.getenv("GEMINI_MODEL", Settings.model_fields["model"].default),
        voice_name=os.getenv("CYRAEN_VOICE", Settings.model_fields["voice_name"].default),
        friday_voice=os.getenv("CYRAEN_FRIDAY_VOICE", "").strip()
        or Settings.model_fields["friday_voice"].default,
        ultron_voice=os.getenv("CYRAEN_ULTRON_VOICE", "").strip()
        or Settings.model_fields["ultron_voice"].default,
        ultron_fx=_env_bool("CYRAEN_ULTRON_FX", True),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        webcam_enabled=_env_bool("WEBCAM_ENABLED", False),
        webcam_index=_env_int("WEBCAM_INDEX", 0),
        screen_enabled=_env_bool("CYRAEN_SCREEN_ENABLED", True),
        wake_word_enabled=_env_bool("CYRAEN_WAKE_WORD", False),
        wake_word_model=os.getenv("CYRAEN_WAKE_WORD_MODEL", "hey_jarvis").strip() or "hey_jarvis",
        wake_word_threshold=float(os.getenv("CYRAEN_WAKE_WORD_THRESHOLD", "0.5") or 0.5),
        wake_window_s=float(os.getenv("CYRAEN_WAKE_WINDOW_S", "8") or 8),
        wake_max_awake_s=float(os.getenv("CYRAEN_WAKE_MAX_AWAKE_S", "90") or 90),
        bridge_hold_s=float(os.getenv("CYRAEN_BRIDGE_HOLD_S", "45") or 45),
        proactive_audio=_env_bool("CYRAEN_PROACTIVE_AUDIO", True),
        session_context_enabled=_env_bool("CYRAEN_SESSION_CONTEXT", True),
        speaker_verify_enabled=_env_bool("CYRAEN_SPEAKER_VERIFY", True),
        speaker_threshold=float(os.getenv("CYRAEN_SPEAKER_THRESHOLD", "0") or 0),
        offline_voice_enabled=_env_bool("CYRAEN_OFFLINE_VOICE", True),
        offline_stt_model=os.getenv("CYRAEN_OFFLINE_STT_MODEL", "").strip(),
        offline_tts=(os.getenv("CYRAEN_OFFLINE_TTS", "auto").strip().lower() or "auto"),
        offline_tts_voice=Path(
            os.getenv("CYRAEN_OFFLINE_TTS_VOICE", "").strip()
            or Settings.model_fields["offline_tts_voice"].default
        ),
        screen_monitor=_env_int("CYRAEN_SCREEN_MONITOR", 1),
        open_apps_via_search=_env_bool("CYRAEN_OPEN_VIA_SEARCH", True),
        type_in_browser=_env_bool("CYRAEN_TYPE_IN_BROWSER", True),
        confirm_before_close=_env_bool("CYRAEN_CONFIRM_CLOSE", True),
        always_on_top=_env_bool("CYRAEN_ALWAYS_ON_TOP", True),
        minimize_to_tray=_env_bool("CYRAEN_MINIMIZE_TO_TRAY", True),
        ui_style=(os.getenv("CYRAEN_UI_STYLE", "hud").strip().lower() or "hud"),
        hud_weather_location=os.getenv("CYRAEN_HUD_WEATHER", "İzmir").strip() or "İzmir",
        boot_style=(os.getenv("CYRAEN_BOOT_STYLE", "orb").strip().lower() or "orb"),
        boot_hold_s=float(os.getenv("CYRAEN_BOOT_HOLD_S", "3") or 3),
        docs_dirs=os.getenv("CYRAEN_DOCS_DIRS", "").strip(),
        startup_sound=_env_bool("CYRAEN_STARTUP_SOUND", True),
        agents_enabled=_env_bool("CYRAEN_AGENTS_ENABLED", True),
        agents_model=os.getenv("CYRAEN_AGENTS_MODEL", Settings.model_fields["agents_model"].default),
        local_llm_enabled=_env_bool("CYRAEN_LOCAL_LLM", True),
        local_llm_url=(
            os.getenv("CYRAEN_LOCAL_LLM_URL", "").strip()
            or Settings.model_fields["local_llm_url"].default
        ),
        local_llm_model=(
            os.getenv("CYRAEN_LOCAL_LLM_MODEL", "").strip()
            or Settings.model_fields["local_llm_model"].default
        ),
        local_llm_small_model=(
            os.getenv("CYRAEN_LOCAL_LLM_SMALL_MODEL", "").strip()
            or Settings.model_fields["local_llm_small_model"].default
        ),
        local_llm_num_ctx=_env_int("CYRAEN_LOCAL_LLM_NUM_CTX", 8192),
        local_llm_timeout=float(_env_int("CYRAEN_LOCAL_LLM_TIMEOUT", 120)),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_workspace_id=os.getenv("ANTHROPIC_WORKSPACE_ID", ""),
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_key=os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_KEY", "")),
        ntfy_topic=os.getenv("NTFY_TOPIC", ""),
        ntfy_server=os.getenv("NTFY_SERVER", "https://ntfy.sh"),
        agents_auto_approve_assisted=_env_bool("CYRAEN_AGENTS_AUTO_APPROVE", True),
        email_address=os.getenv("EMAIL_ADDRESS", ""),
        email_app_password=os.getenv("EMAIL_APP_PASSWORD", os.getenv("EMAIL_PASSWORD", "")),
        email_imap_host=os.getenv("EMAIL_IMAP_HOST", ""),
        email_smtp_host=os.getenv("EMAIL_SMTP_HOST", ""),
        email_smtp_port=_env_int("EMAIL_SMTP_PORT", 0),
        email_sender_name=os.getenv("EMAIL_SENDER_NAME", "CYRAEN"),
        gmail_credentials_file=Path(
            os.getenv("GMAIL_CREDENTIALS_FILE", "").strip()
            or Settings.model_fields["gmail_credentials_file"].default
        ),
        gmail_token_file=Path(
            os.getenv("GMAIL_TOKEN_FILE", "").strip()
            or Settings.model_fields["gmail_token_file"].default
        ),
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", "").strip(),
        spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", "").strip(),
        spotify_redirect_uri=(
            os.getenv("SPOTIFY_REDIRECT_URI", "").strip()
            or Settings.model_fields["spotify_redirect_uri"].default
        ),
        spotify_token_file=Path(
            os.getenv("SPOTIFY_TOKEN_FILE", "").strip()
            or Settings.model_fields["spotify_token_file"].default
        ),
        spotify_default_device=os.getenv("SPOTIFY_DEFAULT_DEVICE", "").strip(),
        mcp_enabled=_env_bool("CYRAEN_MCP", True),
        mcp_config_file=Path(
            os.getenv("CYRAEN_MCP_CONFIG", "").strip()
            or Settings.model_fields["mcp_config_file"].default
        ),
        browser_profile_dir=Path(
            os.getenv("CYRAEN_BROWSER_PROFILE", "").strip()
            or Settings.model_fields["browser_profile_dir"].default
        ),
        browser_headless=_env_bool("CYRAEN_BROWSER_HEADLESS", False),
        browser_blocked_domains=[
            d.strip().lower()
            for d in os.getenv("CYRAEN_BROWSER_BLOCKED", "").replace(";", ",").split(",")
            if d.strip()
        ],
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        # server/config.py TELEGRAM_CHAT_ID kullanir -> geriye uyumlu yedek
        telegram_default_chat_id=(
            os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "").strip()
            or os.getenv("TELEGRAM_CHAT_ID", "").strip()
        ),
        telegram_allowed_chat_ids=[
            c.strip()
            for c in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").replace(";", ",").split(",")
            if c.strip()
        ],
        telegram_auto_reply=_env_bool("TELEGRAM_AUTO_REPLY", True),
        izmir_openapi_token=os.getenv("IZMIR_OPENAPI_TOKEN", "").strip(),
        izmirim_kart_no=os.getenv("IZMIRIM_KART_NO", "").strip(),
        web_console_enabled=_env_bool("CYRAEN_WEB_CONSOLE", True),
        web_console_port=_env_int("CYRAEN_WEB_PORT", 8770),
        web_console_bind=os.getenv("CYRAEN_WEB_BIND", "0.0.0.0"),
        web_console_token=os.getenv("CYRAEN_WEB_TOKEN", ""),
        team_tts_enabled=_env_bool("CYRAEN_TEAM_TTS", True),
        user_name=os.getenv("CYRAEN_USER_NAME", "").strip() or Settings.model_fields["user_name"].default,
        vision_model=os.getenv("CYRAEN_VISION_MODEL", "").strip() or Settings.model_fields["vision_model"].default,
        welcome_voice=os.getenv("CYRAEN_WELCOME_VOICE", "").strip()
        or Settings.model_fields["welcome_voice"].default,
        welcome_text=os.getenv("CYRAEN_WELCOME_TEXT", "").strip()
        or Settings.model_fields["welcome_text"].default,
        audio_mode=os.getenv("CYRAEN_AUDIO_MODE", Settings.model_fields["audio_mode"].default),
        remote_audio_port=_env_int("CYRAEN_REMOTE_AUDIO_PORT", 8771),
        remote_audio_token=os.getenv("CYRAEN_REMOTE_AUDIO_TOKEN", ""),
        phone_audio_enabled=_env_bool("CYRAEN_PHONE_AUDIO", True),
        remote_desktop_enabled=_env_bool("CYRAEN_REMOTE_DESKTOP", False),
        tool_groups_disabled=[g.strip() for g in os.getenv("CYRAEN_TOOLS_OFF", "").split(",") if g.strip()],
        remote_confirm_timeout=float(
            _env_int("CYRAEN_REMOTE_CONFIRM_TIMEOUT", 120)
        ),
        # SCHEDULER_ENABLED, eski CYRAEN_SCHEDULER'in kisa adi (ikisi de gecerli)
        scheduler_enabled=_env_bool("SCHEDULER_ENABLED", _env_bool("CYRAEN_SCHEDULER", True)),
        morning_briefing_time=os.getenv(
            "CYRAEN_MORNING_BRIEFING", Settings.model_fields["morning_briefing_time"].default
        ).strip(),
        morning_briefing_channels=[
            c.strip().lower()
            for c in os.getenv("CYRAEN_MORNING_CHANNELS", "").replace(";", ",").split(",")
            if c.strip()
        ],
        health_check_interval_min=_env_int("CYRAEN_HEALTH_INTERVAL_MIN", 60),
        health_cpu_alert=float(_env_int("CYRAEN_HEALTH_CPU_ALERT", 90)),
        health_mem_alert=float(_env_int("CYRAEN_HEALTH_MEM_ALERT", 90)),
        health_disk_alert=float(_env_int("CYRAEN_HEALTH_DISK_ALERT", 90)),
        maintenance_report_weekly=_env_bool("CYRAEN_MAINTENANCE_REPORT", True),
        daily_summary_time=os.getenv(
            "CYRAEN_DAILY_SUMMARY", Settings.model_fields["daily_summary_time"].default
        ),
        code_exec_enabled=_env_bool("CYRAEN_CODE_EXEC", False),
        adb_enabled=_env_bool("CYRAEN_ADB_ENABLED", True),
        adb_path=os.getenv("CYRAEN_ADB_PATH", Settings.model_fields["adb_path"].default),
        adb_tcp_port=_env_int("CYRAEN_ADB_TCP_PORT", 5555),
        adb_tcp_devices=[
            a.strip()
            for a in os.getenv("CYRAEN_ADB_TCP_DEVICES", "").replace(";", ",").split(",")
            if a.strip()
        ],
        adb_unlock_pin=(
            os.getenv("CYRAEN_ADB_UNLOCK_PIN", "").strip()
            or (get_secret("CYRAEN_ADB_UNLOCK_PIN") or "")
        ),
        gbrain_enabled=_env_bool("CYRAEN_GBRAIN", True),
        okul_enabled=_env_bool("CYRAEN_OKUL_ENABLED", True),
        obsidian_vault=os.getenv("CYRAEN_OBSIDIAN_VAULT", ""),
        obsidian_subdir=os.getenv(
            "CYRAEN_OBSIDIAN_SUBDIR", Settings.model_fields["obsidian_subdir"].default
        ),
        obsidian_log_conversations=_env_bool("CYRAEN_OBSIDIAN_LOG_CONVERSATIONS", True),
    )
    settings.ensure_dirs()
    return settings
