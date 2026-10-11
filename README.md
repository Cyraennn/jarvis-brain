# JARVIS Brain Engine

Gemini Live WebSocket API (`google-genai`, v1alpha) + PyAudio uzerine kurulu, yalnizca
**canli beyin motoruna** odakli moduler yapi. Cift yonlu ses akisi, anlik webcam karesi,
asenkron arac cagirma ve harici ajan koprusu tek bir `asyncio.TaskGroup` icinde yonetilir.

## Gereksinimler
- **Python 3.11+** (`asyncio.TaskGroup`, `ExceptionGroup`)
- Calisan bir mikrofon + hoparlor, opsiyonel webcam
- Google AI Studio API anahtari

Windows'ta PyAudio icin: `pip install pipwin && pipwin install pyaudio` ya da
`pip install pyaudio` (Python 3.11+ icin tekerlek mevcut).

## Kurulum
```bash
cd jarvis-brain
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
copy .env.example .env                              # ve GEMINI_API_KEY doldur
```

## Calistirma

**Masaustu arayuzu (onerilen):**
```bash
python run_ui.py
```
Ses-reaktif HUD kuresi + canli webcam + transkript + sistem/arac logu + kontroller
(mikrofon sustur, kamera ac/kapa, kopru mesaji enjekte et, durdur).

Pencere her zaman ustte durur, kapatinca sistem tepsisine kuculur (tepsi sag-tik:
Goster/Gizle, Her zaman ustte, Windows ile baslat, Cikis). Acilista alkis sesi calar.
"Kendini kapat" komutu (exit_application araci) uygulamayi tamamen kapatir (onaya tabi).

**Sessiz mod (arayuzsuz):**
```bash
python main.py
```
Konusmaya baslayin. `Ctrl+C` ile guvenli kapanir.

**.exe olarak derleme (Windows):**
```bash
build_windows.bat
```
Cikti: `dist/JARVIS/JARVIS.exe`. Ilk calistirmadan once `dist/JARVIS/` icine
`.env` (GEMINI_API_KEY) koyun. `data/`, `bridge/`, log dosyalari exe'nin yaninda olusur.

## Cok-Ajanli Sistem (Orkestrator)

JARVIS (sesli beyin) bir gorevi `dispatch_to_agent` araciyla uzman ajanlara devreder.
Ajanlar Gemini metin modeliyle (varsayilan `gemini-flash-lite-latest`, kota dolunca
otomatik yedek modele gecer) calisir, kendi araclarini kullanir ve sonucu geri iletir.

```
JARVIS sesli beyin ──(dispatch_to_agent)──> bridge/inbox.txt
                                                  │
                                          AgentOrchestrator
                                     (auto ise router uzman secer)
                                                  │
                    ┌──────────┬──────────┬───────┴────┬───────────┐
              arastirmaci   kodcu   bilgisayar_op.  planlayici  sekreter
              (web arama)  (dosya)  (uygulama/yazi)  (devret)   (not)
                                                  │
                                          bridge/outbox.txt
                                                  │
                              JARVIS bunu okuyup sesli aktarir
```

**Calistirma:** `python run_agents.py` (sesli beyinden bagimsiz; ayni anda calisabilir).
Sonraki adimda arayuze entegre edilecek.

**Ajan ozellestirme:** `agents/agents.example.json` -> `agents/agents.json` olarak kopyala.

**Not:** Ajanlar `generate_content` kullanir; ephemeral (`AQ.`) token calisir ama free
tier gunluk limitleri dusuktur (`gemini-3.6-flash` = 20/gun). `-lite` modellerde
limit daha genistir; kalici kullanim icin AI Studio `AIza...` anahtari onerilir.

## Dizin Yapisi
```
jarvis-brain/
├── config/settings.py        # API key, ses modeli, tum konfigurasyon (pydantic)
├── core/
│   ├── brain_engine.py       # Gemini Live baglantisi + 6 paralel asenkron gorev
│   ├── webcam_streamer.py    # Thread-safe latest-frame JPEG yakalayici
│   └── bridge_listener.py    # bridge/outbox.txt izleyici -> canli oturuma enjeksiyon
├── tools/
│   ├── tool_declarations.py  # Gemini Function Declaration tanimlari
│   └── tool_runner.py        # Executor uzerinde tikamadan calisan dispatcher
├── prompts/system_prompt.txt # Karakter + ana talimatlar
├── ui/
│   ├── app.py                # QApplication + motor iscisi + sinyal baglantilari
│   ├── main_window.py        # orb + webcam + transkript + log + kontroller
│   ├── engine_worker.py      # BrainEngine'i ayri thread + asyncio dongusunde calistirir
│   ├── qt_observer.py        # EngineObserver -> Qt sinyal koprusu
│   ├── theme.py              # HUD renk paleti + QSS
│   └── widgets/              # orb.py, webcam_view.py, transcript_view.py, log_view.py
├── bridge/                   # Harici ajan dosya koprusu (outbox / inbox)
├── main.py                   # Sessiz mod asenkron giris noktasi
├── run_ui.py                 # Masaustu arayuzu giris noktasi
├── requirements.txt
└── .env.example
```

## 6 Paralel Gorev (`asyncio.TaskGroup`)
| Gorev | Islevi |
|-------|--------|
| `_send_realtime` | `out_queue` -> canli oturum (mikrofon + webcam Blob paketleri) |
| `_listen_audio` | PyAudio 16 kHz PCM yakalama; model konusurken mikrofon pasif (eko engelleme) |
| `_receive_audio` | Model sesi + transkript + `tool_call` dinleme |
| `_play_audio` | 24 kHz PCM yaniti hoparlorden calma |
| `_stream_webcam_frames` | ~1.5 sn'de bir en guncel webcam JPEG karesi |
| `_stream_screen_frames` | ~2 sn'de bir ekran goruntusu (mss) - "ekran gorusu" |
| `_watch_bridge_inbox` | `bridge/outbox.txt` -> `send_client_content` enjeksiyonu |

Baglanti koparsa exponential-backoff (2s tabanli, 30s tavan, jitter'li) ile sonsuz yeniden baglanir.

## Obsidian Kasa Baglantisi

`.env` icinde `JARVIS_OBSIDIAN_VAULT=<kasa yolu>` tanimlanirsa (varsayilan:
`C:\Users\KULLANICI\Documents\JARVIS Hafiza` - JARVIS'e ayrilmis kasa):
- **Konusmalar**: her tur (Sen / JARVIS) otomatik `Konusmalar/YYYY-MM-DD.md`'ye eklenir
  (`obsidian_log_conversations`, env `JARVIS_OBSIDIAN_LOG_CONVERSATIONS`),
- `remember_note` notlari `Notlar/YYYY-MM-DD.md` gunluk dosyalarina yazar,
- `recall_notes` bu dosyalari da okuyup birlestirir,
- GBrain `kb_write` her kaydin markdown aynasini `GBrain/<baslik>.md` olarak birakir.

`JARVIS_OBSIDIAN_SUBDIR` bos ise dogrudan kasa koku; "JARVIS" verilirse paylasilan
kasada `<vault>/JARVIS/` alt klasoru. Kasa yoksa/tanimsizsa her sey yerel `data/`
altinda calismaya devam eder (sessiz fallback).
Masaustu kisayolu: `scripts/launch_jarvis.vbs` (konsolsuz baslatici) -> Masaustu\JARVIS.lnk.

## Telefondan Kontrol (Web Konsolu + PWA)

`.env`'de `JARVIS_WEB_TOKEN=<gizli>` ZORUNLU (LAN erisimi icin). Ardindan telefon
tarayicisinda: `http://<pc-lan-ip>:8770?key=<token>` (acilista loga yazilir).

- **Telefon gorusmesi** butonu: mikrofon surekli dinler, JARVIS yaniti telefonda
  sesli okunur (Web Speech API). Konusurken mikrofon durur (eko engelleme).
- **Uzak mod**: `POST /api/control {"action":"away_on"}` -> PC mikrofonu + hoparloru
  susar (`BrainEngine.set_output_muted`), gorusme tamamen telefonden. Model yaniti
  yine uretilir, transkript telefona akar.
- **PWA**: sayfa yuklenebilir uygulama - manifest (`/manifest.webmanifest`),
  service worker (`/sw.js`), ikonlar (`assets/generate_pwa_icons.py`). Android
  Chrome'da "Uygulamayi yukle", iOS Safari'de "Ana Ekrana Ekle".
  Otomatik yukleme istemi + cevrimdisi kabuk icin **HTTPS** gerekir (tunel:
  `ngrok http 8770` ya da `tailscale serve`). Duz LAN http'de "Ana ekrana ekle"
  yine tam ekran acar.
- Uzaktan erisim: `ngrok http 8770` (kurulu) veya Tailscale (kalici HTTPS).

## Uzaktan Sunucu Modu (motor lab/uzak bilgisayarda, ses+kontrol evde)

Motoru (Gemini Live, araclar, ajanlar, hafiza) BASKA (surekli acik) bir bilgisayarda
7/24 sunucu gibi calistirip, mikrofon/hoparloru VE tum kontrolu (komut, durum,
onay/red) kendi bilgisayarinizda tutmak icin: `run_server.py` (GUI'siz sunucu
girisi) + `remote_client/` (hafif ses istemcisi) + Tailscale. Kod + hafizayi
(Obsidian kasasi, GBrain, hatirlaticilar, konusma gunlukleri) tek bir USB paketine
hazirlamak icin `python scripts/export_lab_package.py`. Detayli kurulum, guvenlik
notlari ve dogrulama listesi: **[docs/remote_setup.md](docs/remote_setup.md)**.

## Android Cihaz Kontrol (ADB / "Ultron" Modulu)

USB hata ayiklama acik Android telefonlari `adb` uzerinden yonetir. Tamamen asenkron
(`asyncio.create_subprocess_exec`); `adb` yoksa veya cihaz bagli degilse motor
calismaya devam eder, araclar kullanici dostu bir hata dondurur.

- Gereksinim: Android **Platform-Tools** (`adb`) PATH'te. Degilse `.env`'de
  `JARVIS_ADB_PATH=C:\...\platform-tools\adb.exe`. Modulu kapatmak: `JARVIS_ADB_ENABLED=false`.
- Telefonda: Ayarlar -> Gelistirici secenekleri -> **USB hata ayiklama** acik + PC'yi yetkilendir.
- `core/brain_engine.py` acilista `ADBController.probe()` ile durumu loglar
  (`tools/adb_tool.py`, `config.settings`: `adb_enabled` / `adb_path` / `adb_tcp_port` / `adb_tcp_devices`).
- Araclar `device_id` almazsa komut **bagli tum cihazlara** (USB + WiFi) uygulanir
  ("tum telefonlarin kilidini ac", "telefonlarda su sarkiyi cal").

**Kablosuz (WiFi) ADB** — kablo olmadan agdaki telefonlar:
- `.env` -> `JARVIS_ADB_TCP_DEVICES=192.168.1.42,192.168.1.43:5555` (acilista otomatik `adb connect`).
- Araclar: `adb_connect_wifi("192.168.1.42")`, `adb_pair_wifi("ip:port","kod")` (Android 11+
  ilk kez; telefonda *Kablosuz hata ayiklama > Cihazi eslestir*), `adb_enable_wifi(device_id)`
  (USB'den bagli cihazi `tcpip` ile kablosuza gecirir + IP'sini bulup baglanir, sonra kablo cekilir),
  `adb_disconnect_wifi()`.
- WiFi cihazlar `adb devices` listesinde `ip:port` seri olarak gorunur ve diger tum
  araclarla (unlock/open/play/shell) sorunsuz calisir.

## okul (BÖTE Ders Merkezi) Bağlantısı

Ayrı statik web uygulaması `okul/` (ders çalışma suite'i) verisini JARVIS'e bağlar.

- okul → **Ayarlar → JARVIS bağlantısı**: bu PC'nin adresi + `JARVIS_WEB_TOKEN`.
- okul her değişikliğinde tam `localStorage` durumunu `POST /api/okul/push` ile web
  konsoluna gönderir → `data/okul_state.json`. Sekmeye dönünce `GET /api/okul/pull`
  ile JARVIS'in eklediklerini alır (`data/okul_outbox.json`).
- Araçlar: `okul_status` / `okul_next_exams` / `okul_today_tasks` / `okul_schedule` /
  `okul_gpa` / `okul_search_notes` (okuma), `okul_add_task` / `okul_add_exam` (yazma).
- Yalnız `run_ui.py` (web konsolu) ile çalışır. `config.settings`: `okul_enabled`,
  `okul_state_path`, `okul_outbox_path`. Bağlı değilse araçlar kullanıcı dostu hata döner.

## WhatsApp Kolu (`core/whatsapp_handler.py`)

Playwright ile `web.whatsapp.com` üzerinden kalıcı tarayıcı oturumu (QR bir kez).
`main.py` çalışırken beyin motoruyla aynı `asyncio.TaskGroup` içinde döner; hata
alırsa beyni etkilemeden yeniden bağlanır.

```bash
pip install playwright && playwright install chromium
copy config\whatsapp.example.json config\whatsapp.json   # doldur, "enabled": true
python main.py                                            # ilk açılışta QR okut
```

- **Multimedya:** gelen **sesli mesaj** → `data/whatsapp_media/`'ye iner → Gemini
  multimodal ile metne dökülür (ayrı Whisper gerekmez) → LLM yanıtlar. Gelen
  **görsel** → indirilir → Gemini Vision analiz eder → yanıt. Medya işlenince
  otomatik silinir; açılışta eski artıklar süpürülür (`media_retention_minutes`).
- **Hafıza:** kişi başına son `history_size` mesaj (`ConversationMemory`). Sistem
  prompt'u WhatsApp'a özel: kısa, doğal, kullanıcının üslubunda.
- **İnsan simülasyonu:** yanıttan önce uzunlukla orantılı 2–6 sn bekleme +
  Playwright ile kademeli yazım ("yazıyor…" görünür).
- **Rol tabanlı yetki:** `admin_numbers` (tüm komutlar), `allowed_contacts`
  (`whitelist_mode`: `list`/`all`/`off` — sadece otomatik yanıt), diğerleri
  yoksayılır. `blacklisted_words` içeren mesajlar atlanır + admin'e bildirilir.
- **Yönetici komutları** (admin numarasından): `JARVIS durum`,
  `JARVIS modu [otomatik|manuel|sessiz]`, `JARVIS sessiz`,
  `JARVIS mikrofon aç/kapat`, `JARVIS hoparlör aç/kapat`, `JARVIS söyle: <metin>`
  (canlı beyne enjekte), `JARVIS ajan: <görev>` (ajan kuyruğu), `JARVIS hafıza sil`,
  `JARVIS kapat`.
- **Köprü aynası:** gelen/giden her mesaj `bridge/outbox.txt`'e `[WHATSAPP] …`
  olarak yazılır — canlı sesli beyin olan biteni duyar.
- Ayarlar: `config/whatsapp.json` (gitignore'da; şema için `whatsapp.example.json`).
  Env override: `JARVIS_WHATSAPP_ENABLED`, `JARVIS_WHATSAPP_HEADLESS`.
- Yardımcı modül: `core/media_utils.py` (`transcribe_audio`, `describe_image`,
  `MediaVault` auto-cleanup).

> WhatsApp Web DOM sınıfları sık değişir. Tüm seçiciler `whatsapp_handler.py`
> içindeki `SEL` sözlüğünde toplanmıştır; bir şey çalışmazsa önce orayı güncelleyin.

## Araclar
`get_current_datetime`, `get_system_status`, `list_directory`, `read_text_file`,
`remember_note`, `recall_notes`, `dispatch_to_agent`,
`open_application` (Windows arama cubuguna harf harf yazip acar),
`open_website` (tarayici cubuguna harf harf yazar), `open_path`,
`type_in_search`, `type_in_browser`,
`type_text` (odaktaki veya adiyla bulunan uygulamaya harf harf yazar),
`click_at` / `move_mouse` / `scroll` / `press_keys` (ekrani gorup 0-1000 normalize
koordinatla dogru alana tikla, sonra yaz),
`clear_field` / `drag_select` / `select_word` / `select_line` / `erase_chars`
(soylenen yeri sec ve sil),
`close_application` / `close_active_tab` (NAZIK kapatma, kullanici onayina tabi),
`exit_application` (JARVIS kendini kapatir, onaya tabi),
`adb_list_devices` / `adb_connect_wifi` / `adb_pair_wifi` / `adb_enable_wifi` /
`adb_disconnect_wifi` / `adb_unlock_device` / `adb_open` / `adb_play_media` / `adb_shell`
(Android ADB Control "Ultron" modulu - USB + WiFi bagli telefon(lar)i yonetir;
`device_id` verilmezse BAGLI TUM CIHAZLARA uygulanir),
`okul_status` / `okul_next_exams` / `okul_today_tasks` / `okul_schedule` / `okul_gpa` /
`okul_search_notes` / `okul_add_task` / `okul_add_exam` (BÖTE Ders Merkezi koprusu).

Kapatma onayi arayuzde modal bir pencereyle sorulur; `confirm_before_close=false`
(env `JARVIS_CONFIRM_CLOSE=false`) ile devre disi birakilabilir. Harf harf yazma
`open_apps_via_search` / `type_in_browser` ayarlariyla kapatilip dogrudan acmaya
donulebilir (hiz: `search_type_delay`, `browser_type_delay`).

Yeni arac eklemek icin: `tool_declarations.py`'ye bir `FunctionDeclaration`,
`tool_runner.py`'ye `register(...)`.
