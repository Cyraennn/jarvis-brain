# Uzaktan Sunucu Modu: JARVIS lab bilgisayarında, kontrol evde

Bu kurulum, JARVIS motorunu (Gemini Live bağlantısı, araçlar, ajanlar, WhatsApp
kolu vb.) **lab bilgisayarında** 7/24 çalışan bir "sunucu" olarak tutarken, **sesi
ve tüm kontrolü evdeki bilgisayarınızda** bırakır.

```
EV BILGISAYARI                          LAB BILGISAYARI
┌─────────────────────────┐  Tailscale  ┌──────────────────────────────┐
│ remote_client/           │◄───(VPN)───►│ run_server.py                 │
│  run_remote_client.py    │             │  - BrainEngine (Gemini Live)  │
│  - mikrofon -> WS        │  ws://8771  │  - net/audio_server.py        │
│  - WS -> hoparlor        │◄───────────►│  - web/console_server.py      │
│                           │             │  - orkestrator + zamanlayici  │
│ Tarayici (web konsolu)   │  http://8770│                                │
│  - komut / durum / onay  │◄───────────►│                                │
└─────────────────────────┘             └──────────────────────────────┘
```

Motor lab'da çalıştığı için **webcam/ekran görüşü de lab'daki donanımı kullanır**
(evdekini değil) — bunu istemiyorsanız aşağıda "Webcam/ekran" bölümüne bakın.

Lab bilgisayarı **sürekli açık** kalacağı için hafıza da (Obsidian kasası, GBrain,
hatırlatıcılar/rutinler, okul durumu, konuşma günlükleri, WhatsApp ayarı) oraya
taşınır — motor TÜM işlemleri orada yapar, ev bilgisayarı **sadece girdi/çıktı**
(mikrofon + hoparlör + kontrol ekranı) olur.

## 0. Kod + hafızayı lab bilgisayarına taşı (USB)

Bu makinede (evde), tek bir zip hazırlayan betiği çalıştırın:

```bash
cd jarvis-brain
python scripts/export_lab_package.py
```

Bu komut:
- `multi/jarvis-lab-package-<tarih>.zip` dosyasını oluşturur — içinde **tüm kod**
  (`.venv`/`__pycache__`/`build`/`dist` hariç), **`data/`** (GBrain notları,
  hatırlatıcı/rutinler, okul durumu, konuşma günlükleri, `config/whatsapp.json` —
  `data/whatsapp_session/` ~127MB olduğu için ve WhatsApp genelde kapalı olduğu için
  varsayılan HARİÇ, istersen `--include-whatsapp-session` ekle), **Obsidian kasası**
  (`JARVIS_OBSIDIAN_VAULT`) ve **`.env.for-lab`** (mevcut `.env`'iniz + uzak-sunucu
  ayarları otomatik eklenmiş) bulunur.
- Aynı anda BU makinedeki `remote_client/.env`'i **yeni rastgele tokenlarla**
  günceller (veya script tekrar çalıştırılırsa var olanları korur) — bu tokenlar
  zip içindeki `.env.for-lab`'daki tokenlarla **önceden eşleşir**, elle kopyalama
  hatası riski olmaz.

Zip'i USB ile lab bilgisayarına taşıyın, **tam olarak `C:\JARVIS\`** altına çıkartın:
```
C:\JARVIS\jarvis-brain\   <- kod + data/
C:\JARVIS\Hafiza\         <- Obsidian kasası
```
(Zip içindeki `README.txt`'te aynı adımlar özetlenir.) Ardından lab'da:
```bash
cd C:\JARVIS\jarvis-brain
ren .env.for-lab .env
```

> **Güvenlik:** zip, `.env` içindeki tüm gizli anahtarları (GEMINI_API_KEY, e-posta
> uygulama şifresi, ADB PIN, yeni web/ses tokenları) düz metin taşır. USB'yi
> kimseyle paylaşmayın; aktarımdan sonra zip'i (ve USB'deki kopyasını) silin.
>
> **Not (okul bağlantısı):** `okul/assets/js/config.js` içinde JARVIS için önceden
> hardcode edilmiş bir `JARVIS_WEB_TOKEN` varsa, bu script YENİ bir token üretip
> eskisinin üzerine yazar (dotenv "son satır kazanır" kuralı) — okul uygulamasını da
> yeni token'a göre güncellemeniz gerekir, aksi halde okul köprüsü bağlanamaz.

## 1. Tailscale kurulumu (her iki bilgisayarda)

İki bilgisayar farklı ağlarda (okul lab / ev) olduğu için port yönlendirme yerine
[Tailscale](https://tailscale.com) (WireGuard tabanlı mesh VPN, NAT arkasında da
çalışır, ücretsiz) kullanılır.

1. Her iki bilgisayara Tailscale'i kurun, aynı hesapla `tailscale up`.
2. Lab bilgisayarında `tailscale status` ile MagicDNS adını not edin
   (örnek: `lab-pc.tailxxxxx.ts.net`) — bu, aşağıda `JARVIS_SERVER_HOST` olacak.
3. Ev bilgisayarından lab'a `ping lab-pc.tailxxxxx.ts.net` ile bağlantıyı doğrulayın.

## 2. Lab bilgisayarı (sunucu)

Kod + `.env` + hafıza zaten "0. Adım"daki zip ile `C:\JARVIS\` altına geldi ve
`.env.for-lab` → `.env` olarak yeniden adlandırıldı (token'lar ve
`JARVIS_AUDIO_MODE=network`/`JARVIS_WEB_BIND=0.0.0.0`/`JARVIS_OBSIDIAN_VAULT` zaten
içinde). Sadece bağımlılıkları kurun:

```bash
cd C:\JARVIS\jarvis-brain
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
```

`run_server.py`, `JARVIS_AUDIO_MODE=network` iken `JARVIS_WEB_TOKEN`/
`JARVIS_REMOTE_AUDIO_TOKEN` boşsa **başlamayı reddeder** (aksi halde sunucular
sessizce sadece localhost'a kapanır ve ev bilgisayarından hiç erişilemez) — normal
şartlarda zip'ten geldiği için bu ikisi zaten dolu olmalı.

Windows Güvenlik Duvarı'nda gelen kurallar ekleyin (mümkünse Tailscale arayüzüyle
sınırlı): TCP `8770` (web konsolu) ve TCP `8771` (uzak ses).

Başlatma:
```bash
python run_server.py
```
Log'da `Web konsolu: http://<ip>:8770?key=...` ve `Uzak ses sunucusu dinliyor: ws://...`
satırlarını görmelisiniz.

**Otomatik başlatma (Task Scheduler, oturum açılışında):**
```bat
schtasks /create /sc onlogon /tn "JARVIS-Server" ^
  /tr "C:\JARVIS\jarvis-brain\.venv\Scripts\pythonw.exe C:\JARVIS\jarvis-brain\run_server.py" ^
  /rl highest
```
(gerekirse `/it` ile etkileşimli oturum bayrağı ekleyin.)

## 3. Ev bilgisayarı (istemci)

`remote_client/.env` zaten "0. Adım"da `export_lab_package.py` tarafından oluşturuldu
ve `JARVIS_REMOTE_AUDIO_TOKEN`/`JARVIS_WEB_TOKEN` lab'dakiyle ÖNCEDEN eşleşiyor —
sadece Tailscale kurulduktan sonra `remote_client/.env` içindeki boş
`JARVIS_SERVER_HOST` satırını lab'ın MagicDNS adıyla doldurmanız yeterli:

```bash
cd remote_client
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
```

Başlatma:
```bash
python run_remote_client.py
```
Varsayılan tarayıcıda web konsolu otomatik açılır; konsolda `BAGLANDI` mesajı
görünce mikrofonunuza konuşabilirsiniz.

## 4. Doğrulama sırası

1. **Tek makinede duman testi** (Tailscale'e geçmeden önce): `run_server.py`'yi
   `JARVIS_WEB_BIND=127.0.0.1` ile aynı bilgisayarda başlatın, `remote_client`'i de
   aynı bilgisayarda `JARVIS_SERVER_HOST=127.0.0.1` ile çalıştırın. Ses round-trip'i
   ve web konsolu bu şekilde ağ değişkenleri olmadan doğrulanabilir.
2. **Tailscale bağlantısı**: `ping <lab tailscale adı>` evden çalışıyor mu?
3. **Sunucu ayakta**: lab'da `run_server.py` loglarında web konsolu + ses sunucusu
   satırları var mı?
4. **İstemci bağlanıyor**: `remote_client` çalıştırıldığında lab tarafındaki logda
   `Uzaktan ses istemcisi baglandi.` görünüyor mu?
5. **Ses**: gerçek bir cümle söyleyip JARVIS'in evdeki hoparlörden yanıt verdiğini
   duyun.
6. **Onay akışı**: onay gerektiren bir eylem tetikleyin (örn. "Not defteri
   uygulamasını kapat" -> `close_application`, `confirm_before_close=True`
   varsayılan açık). Web konsolunda kırmızı "ONAY BEKLİYOR" kartı çıkmalı;
   Onayla/Reddet butonlarının ikisini de test edin. Hiçbir şeye basmadan
   `remote_confirm_timeout` (varsayılan 120 sn) kadar bekleyin — eylem
   **otomatik REDDEDİLMELİ** (headless/paylaşımlı makinede bilinçli güvenlik
   varsayılanı; asla otomatik onaylanmaz).

## 5. Güvenlik notları

- Lab bilgisayarı paylaşımlı/kurumsal olabilir: `code_exec_enabled` varsayılan
  **kapalı** kalsın, `confirm_before_close`/`agents_require_approval` **açık**
  kalsın. Uzaktan onay zaman aşımında her zaman **reddeder**, otomatik onaylamaz.
- `JARVIS_WEB_TOKEN` ve `JARVIS_REMOTE_AUDIO_TOKEN` uzun/rastgele olmalı, kimseyle
  paylaşmayın, `.env` dosyaları git'e eklenmemeli (zaten `.gitignore`'da).
- Webcam/ekran görüşü lab makinesinde kalır (motor orada çalıştığı için). İstemiyorsanız
  lab `.env`'inde `WEBCAM_ENABLED=false` ve `JARVIS_SCREEN_ENABLED=false` ayarlayın.
- Ev↔okul ağ sıçraması nedeniyle ses gecikmesi tam-yerel deneyimden yüksek olacaktır;
  bağlantı tamamen koparsa (`remote_client` üstel geri-çekilmeyle otomatik yeniden
  dener) konuşma yeniden bağlanana kadar duraklar.

## 6. Sorun giderme

| Belirti | Olası neden |
|---|---|
| İstemci `401` alıyor | `JARVIS_REMOTE_AUDIO_TOKEN`/`JARVIS_WEB_TOKEN` iki tarafta eşleşmiyor |
| İstemci `409` alıyor | Ses sunucusuna zaten başka bir istemci bağlı (tek istemci desteklenir) |
| Bağlantı zaman aşımı / `ConnectionRefused` | Tailscale ping çalışmıyor, veya güvenlik duvarı 8770/8771'i engelliyor |
| `run_server.py` hemen `SystemExit` ile kapanıyor | `JARVIS_AUDIO_MODE=network` ama tokenlardan biri boş |
| Ses hiç gelmiyor ama bağlantı "BAGLANDI" diyor | Lab tarafında `GEMINI_API_KEY` geçersiz/kota dolu - `run_server.py` logunda "Oturum hatasi" var mı kontrol edin |
