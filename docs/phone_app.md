# CYRAEN telefon uygulaması (Android)

Telefon, PC'deki CYRAEN'in **gövdesi**: beyin (Gemini Live), araçlar ve hafıza PC'de çalışır;
telefon mikrofon/hoparlör, ekran ve telefon eylemleri sağlar. Kaynak: `C:\dev\cyraen-android`
(Kotlin + Compose, paket `com.sezai.cyraen`).

```
TELEFON                                         PC (python run_ui.py)
 orb + harita (web3d, APK'ya gömülü)             BrainEngine + ~140 araç
 mikrofon/hoparlör ── ws :8771 PCM ──────────►   SwitchableAudioTransport (PC ⇄ telefon)
 SSE :8770/api/events?client=phone ◄──────────   BUS: transcript, panel, phone_action, file
 POST /api/say · /api/phone-result · /api/files/* · /api/remote/input
 GET  /api/screen/stream (MJPEG)
            └──────── Tailscale: evde de dışarıda da aynı adres ────────┘
```

## Kurulum

1. **Tailscale**: PC'ye ve telefona kurun, aynı hesapla giriş yapın. PC'nin Tailscale IP'si
   (`100.x.y.z`) telefondaki "PC adresi" olur. Evde de mobil veride de aynı adres çalışır.
2. **PC `.env`**: `CYRAEN_WEB_TOKEN` dolu olmalı (telefondaki "Token"); `CYRAEN_WEB_BIND=0.0.0.0`.
   Ses sunucusu ayrı token istemez (`CYRAEN_REMOTE_AUDIO_TOKEN` boşsa web token'ı kullanılır).
   - Uzaktan ekran/kontrol için: `CYRAEN_REMOTE_DESKTOP=1` (varsayılan kapalı).
   - Telefon sesini kapatmak için: `CYRAEN_PHONE_AUDIO=0`.
3. **Güvenlik duvarı** (yönetici PowerShell, bir kez):
   ```powershell
   New-NetFirewallRule -DisplayName "CYRAEN telefon 8770-8771" -Direction Inbound -Protocol TCP -LocalPort 8770,8771 -Action Allow -RemoteAddress 100.64.0.0/10
   ```
   (`100.64.0.0/10` = yalnızca Tailscale ağı.)
4. **APK**: `C:\dev\cyraen-android\app\build\outputs\apk\debug\app-debug.apk` → telefona kur
   (USB'de `adb install -r app-debug.apk`). Açılışta adres + token gir, izinleri ver.

## Özellikler → PC tarafı

| Telefonda | PC kodu |
|---|---|
| Canlı ses (mikrofon düğmesi / orb hapı) | `core/audio_transport.py::SwitchableAudioTransport`, `net/audio_server.py`, `ui/engine_worker.py::_build_audio` |
| Paneller (3B harita/rota, hava, haber, grafik, bilgi kartı) | `ui/qt_observer.py::on_panel` → `BUS "panel"` (yerel `path` atılır) |
| "Buradan Alsancak'a rota" | `tools/panel_tools.py::_locate` (`konumum` → telefon GPS) |
| Arama, SMS, alarm, zamanlayıcı, uygulama aç, konum, pil, telefonu çaldır | `tools/phone_tools.py` → `web/phone_link.py` (SSE `phone_action` ↔ `POST /api/phone-result`) |
| Dosya: telefondan PC'ye (Paylaş → CYRAEN) / PC'den telefona ("telefonuma at") | `web/phone_files.py`, `send_file_to_phone` |
| PC ekranı + dokunarak kontrol | `web/remote_desktop.py` (MJPEG ~10 fps, girdi `tools/keyboard_input.py`) |

Arama ve SMS telefonda her zaman onay kartı ister. Telefon bağlı değilse telefon araçları
hemen hata döner (CYRAEN "aradım" diyemez).

## Bilinen sınırlar

- Android, arka plandaki uygulamanın ekran açmasını engeller: uygulama kapalıyken gelen
  alarm/uygulama açma istekleri bildirim olarak gelir, dokununca tamamlanır.
- Ses sunucusu tek istemci kabul eder (409): `remote_client` ile telefon aynı anda bağlanamaz.
- PC kapalıysa telefon CYRAEN'e ulaşamaz (bağımsız mod kaldırıldı).

## Saat (Galaxy Watch FE / Wear OS)

Saat PC'ye **kendisi bağlanmaz**; telefon üzerinden çalışır. Kaynak: `C:\dev\cyraen-android\wear`
(aynı projede `:wear` modülü, paket yine `com.sezai.cyraen`).

```
SAAT (:wear)                                   TELEFON (:app)                       PC
 orb (bas-konuş) ── /cyraen/audio 16k PCM ──►   LiveAudio.feedMic ── ws :8771 ──►   BrainEngine
 hoparlör        ◄── /cyraen/audio 24k PCM ──   LiveAudio.watchTap
 döküm + onaylar ◄── /cyraen/state (JSON) ───   WearBridge ← CyraenLink (SSE :8770)
 ✓ / ✕           ── /cyraen/confirm ────────►   CyraenLink.confirm → POST /api/confirm
          └── Bluetooth / Wi-Fi (Wearable Data Layer) ──┘
```

- Saatte uygulama açıkken ses saate yönlenir: telefon mikrofonu kapanır, CYRAEN'in cevabı saat
  hoparlöründen çalar. Uygulamadan çıkınca ses telefona döner. PC tek istemci (telefon) görür, 409 olmaz.
- Kadran Tile'ı ("CYRAEN"): dokununca uygulama açılır ve hemen dinlemeye başlar.
- Onay isteyen işlemler (arama, SMS, kapatma) saatte titreşimli ✓ / ✕ kartı olarak da çıkar.
- PC tarafında değişiklik gerekmez.

### Kurulum

1. Derle: `cd C:\dev\cyraen-android; .\gradlew :app:assembleDebug :wear:assembleDebug`
   (iki APK aynı bilgisayarda derlenmeli: Data Layer aynı paket adı + aynı imza ister.)
2. Saatte geliştirici modu: Ayarlar → Saat hakkında → Yazılım bilgisi → "Yazılım sürümü"ne 5 kez dokun.
   Geliştirici seçenekleri → ADB hata ayıklama + Kablosuz hata ayıklama (saat ve PC aynı Wi-Fi'de).
3. `adb pair <ip:eşleşme-portu>` (saatte gösterilen kodla), sonra `adb connect <ip:port>`.
4. Yükle: telefon `adb -s <telefon> install -r app\build\outputs\apk\debug\app-debug.apk`,
   saat `adb -s <saat> install -r wear\build\outputs\apk\debug\wear-debug.apk`.
5. Telefonda CYRAEN açık ve PC'ye bağlı olsun → saatte CYRAEN'i aç, mikrofon iznini ver.

### Bilinen sınırlar

- Telefonda CYRAEN çalışmıyorsa saatte "Telefonda CYRAEN'i aç" yazar (Android, arka plandan
  mikrofonlu servis başlatmaya izin vermez; ama ses saatten geldiği için telefon mikrofonu gerekmez).
- Saat ekranı kapanınca ses kanalı kapanır; uzun cevaplarda ekranı açık tut.
