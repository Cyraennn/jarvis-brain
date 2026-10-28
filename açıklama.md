# JARVIS Çoklu Ajan Sistemi: Kurulum Rehberi

Bu rehber, yeni eklenen özellikleri (OpenRouter çoklu model, Gmail, Telegram, İzmir ulaşım) çalıştırmak için **senin yapman gerekenleri** sırayla anlatır. Bütün komutlar `jarvis-brain` klasöründe çalıştırılır.

> Kısaca: Adım 1 ve 2 zorunlu. Telegram (Adım 3), Gmail (Adım 4) ve Ulaşım (Adım 5) birbirinden bağımsız. Hangisini kurarsan o çalışır, kurmadıkların sistemi bozmaz.

---

## 0. Ne eklendi?

**Her ajanın kendi modeli var** (`agents/agents.json`):

| Ajan | Görevi | Ana model | Yedek |
|---|---|---|---|
| `arastirmaci` | Araştırma, uzun doküman özeti | `nvidia/nemotron-3-ultra-550b-a55b:free` | Gemini Flash Lite |
| `kodcu` | Kod yazma, inceleme | `claude-opus-5-5` (Claude, ücretli) | `qwen/qwen3.8-27b:free` → Gemini |
| `bilgisayar_op` | Terminal / sistem | `claude-opus-5-5` (Claude, ücretli) | `nvidia/nemotron-3-super-120b-a12b:free` → Gemini |
| `planlayici` | İşi alt görevlere bölme | `openrouter/free` | Gemini zinciri |
| `sekreter` | Gmail + Telegram + notlar | `openrouter/free` | Gemini zinciri |
| `ulasim` | ESHOT, rota, İzmirim Kart | `openrouter/free` | Gemini Flash Lite |

**Eklentilerin de kendi modeli var** (`agents.json` içindeki `channels` bölümü):

| Eklenti | Model |
|---|---|
| Telegram otomatik yanıt | `openrouter/free` |
| Gmail yanıt taslağı | `nvidia/nemotron-3-ultra-550b-a55b:free` |

Bir model hata verirse ya da kotası dolarsa sıradaki yedeğe geçilir. Yazılım ajanlarında sıra Claude → OpenRouter → Gemini; Claude çalışmazsa (anahtar yok, bakiye bitti, istek reddedildi) iş OpenRouter'a, o da çalışmazsa Gemini'ye devredilir. Hiçbir zaman tek bir modele bağlı kalmazsın.

> **Sesli beyin neden hâlâ Gemini?** Gerçek zamanlı konuşup aynı anda araç çağırabilen (Gemini Live) başka bir model yok. Ajanlar ve eklentiler ise istediğin modeli kullanabilir.

---

## Adım 1: Paketleri kur (zorunlu)

```bash
pip install -r requirements.txt
```

Yeni eklenen paketler şunlar: `openai` (OpenRouter için), `httpx`, `google-api-python-client`, `google-auth-oauthlib`.

---

## Adım 2: OpenRouter anahtarı (zorunlu, zaten yapılmış)

`.env` dosyanda `OPENROUTER_API_KEY` zaten tanımlı. Değiştirmek istersen:

1. https://openrouter.ai/keys adresine git ve **Create Key** ile yeni bir anahtar oluştur.
2. `.env` dosyasında şu satırı güncelle:
   ```
   OPENROUTER_API_KEY=sk-or-...
   ```

`.env`'deki `OPENROUTER_MODEL` satırı, Telegram ve Gmail zincirlerinde kanal modelinden sonra denenecek modeldir. Silersen varsayılan zincir kullanılır.

> Anahtar yoksa ya da geçersizse sistem çökmez. Ajanlar Gemini'ye düşer ve log'a `YEDEK MODELE GECILIYOR` yazar.

---

## Adım 3: Telegram botu (isteğe bağlı)

### 3.1 Bot oluştur
1. Telegram'da **@BotFather**'ı aç ve `/newbot` yaz.
2. Bota bir ad ve sonu `bot` ile biten bir kullanıcı adı ver (örnek: `benim_jarvis_bot`).
3. BotFather'ın verdiği **token**'ı kopyala. `123456789:AA...` gibi görünür.

### 3.2 Kendi chat id'ni bul
1. Yeni botuna Telegram'dan herhangi bir mesaj at (örnek: "selam").
2. Tarayıcıda şu adresi aç (`<TOKEN>` yerine kendi token'ını yaz):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Çıkan metinde `"chat":{"id":123456789` kısmındaki sayı senin **chat id**'ndir.

### 3.3 `.env`'e yaz
```
TELEGRAM_BOT_TOKEN=123456789:AA...
TELEGRAM_DEFAULT_CHAT_ID=123456789

# İsteğe bağlı:
# TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321   # otomatik yanıt verilecek sohbetler
# TELEGRAM_AUTO_REPLY=false                       # sadece bildirim, otomatik yanıt yok
```

### Nasıl davranır?
- Bota gelen **her** mesaj JARVIS'e `[TELEGRAM] kişi: mesaj` olarak iletilir ve JARVIS bunu sesli söyler.
- **Otomatik yanıt yalnızca izinli sohbetlere** gider. `TELEGRAM_ALLOWED_CHAT_IDS` boşsa bu sadece senin sohbetindir (`TELEGRAM_DEFAULT_CHAT_ID`). Yabancılar bota yazarsa JARVIS sana haber verir ama onlara cevap vermez.
- JARVIS'e sesle "Telegram'dan şunu gönder" dersen önce metni okur, sonra **onay penceresi** açılır.

> Uyarı: Aynı bot token'ını aynı anda iki programda dinletme. Telegram buna `409 Conflict` hatasıyla karşılık verir.

---

## Adım 4: Gmail OAuth (isteğe bağlı)

Bu adımı yapmazsan e-posta araçları eskisi gibi IMAP ile (`EMAIL_ADDRESS` + `EMAIL_APP_PASSWORD`) çalışmaya devam eder. Gmail API daha güvenlidir ve **taslak oluşturma** ile **üslubunda yanıt taslağı** özelliklerini açar.

### 4.1 Google Cloud ayarı (bir kez)
1. https://console.cloud.google.com adresine git ve üstteki proje seçiciden **Yeni Proje** oluştur (örnek: `jarvis`).
2. **API'ler ve Hizmetler → Kitaplık** bölümünde **Gmail API**'yi aratıp **Etkinleştir**'e bas.
3. **OAuth izin ekranı** ayarı:
   - Kullanıcı türü: **Harici (External)**
   - Uygulama adı: `JARVIS`; destek e-postası: kendi adresin
   - **Test kullanıcıları** bölümüne kendi Gmail adresini ekle.
4. **Kimlik Bilgileri → Kimlik bilgisi oluştur → OAuth istemci kimliği** yolunu izle:
   - Uygulama türü: **Masaüstü uygulaması**
   - Oluşturduktan sonra **JSON'u indir**.
5. İndirdiğin dosyayı şu adla kaydet:
   ```
   jarvis-brain/config/gmail_credentials.json
   ```

### 4.2 Yetki ver (bir kez)
```bash
python scripts/gmail_auth.py
```
- Tarayıcı açılır. Gmail hesabını seçip izin ver.
- "Google bu uygulamayı doğrulamadı" uyarısı çıkarsa **Gelişmiş → JARVIS'e git (güvenli değil)** yolunu seç. Bu normaldir, uygulama senin kendi uygulaman.
- Sonunda terminalde `Yetkilendirme tamam` yazısını ve son 3 okunmamış mailini görürsün.
- Token `data/gmail_token.json` dosyasına kaydedilir ve süresi dolunca kendiliğinden yenilenir.

Dosyaları başka bir yerde tutmak istersen `.env`'e şunları yaz:
```
GMAIL_CREDENTIALS_FILE=C:\yol\gmail_credentials.json
GMAIL_TOKEN_FILE=C:\yol\gmail_token.json
```

---

## Adım 5: Ulaşım (isteğe bağlı)

Durak arama, yakındaki duraklar, hat saatleri ve rota **hiçbir ayar yapmadan** çalışır. İlk kullanımda İzmir açık verisi (yaklaşık 6 MB) indirilir ve 7 gün saklanır.

İsteğe bağlı olarak `.env`'e şunları ekleyebilirsin:
```
IZMIRIM_KART_NO=1234567890        # bakiye sayfası açılırken JARVIS söyler
IZMIR_OPENAPI_TOKEN=...           # canlı otobüs konumu için
```
- **İzmirim Kart:** Açık bir bakiye servisi olmadığı için JARVIS resmi bakiye sayfasını açar. Bakiyeyi sesli okuyamaz.
- **Canlı otobüs:** İzmir'in canlı otobüs servisi artık token istiyor. Token yoksa JARVIS bunu söyler ve tarife saatlerini verir.

---

## Adım 5b: Spotify (isteğe bağlı, Premium gerekir)

1. https://developer.spotify.com/dashboard → **Create app** → Redirect URI: `http://127.0.0.1:8888/callback`, "Web API" işaretli.
2. Client ID ve Client Secret'ı **doğrudan** `.env`'e yaz (sohbete yapıştırma):
   ```
   SPOTIFY_CLIENT_ID=...
   SPOTIFY_CLIENT_SECRET=...
   # İsteğe bağlı: SPOTIFY_DEFAULT_DEVICE=pc   (pc | telefon | cihaz adı)
   ```
3. `pip install spotipy` → `python scripts/spotify_auth.py` → tarayıcıda izin ver.

Sonra: "Danza Kuduro çal", "sıradaki", "ne çalıyor", "sesi 30 yap", "telefonda çal".
Spotify kapalıysa JARVIS PC'deki uygulamayı açıp çalar (zamanlı görevler dahil).

---

## Adım 5c: MCP entegrasyonları (isteğe bağlı)

JARVIS, Claude Desktop biçimindeki herhangi bir MCP sunucusuna bağlanabilir (GitHub, Notion, takvim, dosya sistemi…).

1. `config/mcp_servers.example.json` dosyasını `config/mcp_servers.json` olarak kopyala.
2. İstediğin sunucuyu ekle veya `"disabled": true` satırını kaldır. Token'ları JSON'a değil `.env`'e yaz; JSON'da `${GITHUB_TOKEN}` gibi başvur.
3. `confirm` alanı: `write` (varsayılan; yazan, silen ve gönderen araçlar onay penceresi açar), `all` (her çağrı onaylı) veya `none`.
4. npx ile çalışan sunucular Node.js ister. Sunucu günlükleri `data/logs/mcp_<ad>.log` dosyasına yazılır.

Dene: "MCP sunucularım neler?" ya da "MCP ile masaüstündeki dosyaları listele".
Ajanlar (`entegrasyon_uzmani`) yalnızca onay gerektirmeyen araçları çalıştırabilir.

## Adım 5d: Tarayıcı ajanı

`playwright install chromium` komutunu bir kez çalıştır. JARVIS ayrı bir kalıcı profil kullanır (`data/browser_profile`).
Giriş gerektiren bir site için ilk seferde açılan pencerede **elle giriş yap**; profil oturumu hatırlar.

Dene: "eshot.gov.tr'ye gir, 5 numaralı hattın duyurularına bak".
Bu istek `web_operatoru` ajanına gider. Ajan ödeme, satın alma, silme ve şifre girişi yapmaz.
İsteğe bağlı `.env` ayarları: `JARVIS_BROWSER_HEADLESS=true` (pencere gizli), `JARVIS_BROWSER_BLOCKED=site1.com,site2.com`.

## Adım 6: Çalıştır

| Komut | Ne yapar |
|---|---|
| `python run_ui.py` | Masaüstü arayüzü (sesli beyin + ajanlar + Telegram kolu) |
| `python main.py` | Arayüzsüz sesli beyin (+ WhatsApp/Telegram kolları) |
| `python run_server.py` | Uzak sunucu modu |
| `python run_agents.py` | Sadece ajan orkestratörü (test için) |

Başarılı bir açılışta log'da şu satırları görürsün:
- `OpenRouter (aktif): sekreter, ulasim, ...`: ajanlar OpenRouter'a bağlı.
- `[TG] Telegram kolu aktif`: Telegram dinleniyor (yalnızca token varsa).

---

## Adım 7: Dene

JARVIS'e sesle şunları söyleyebilirsin:

**E-posta**
- "Okunmamış maillerim var mı?"
- "Hocadan gelen maile kibar bir cevap taslağı hazırla." (Gmail'e taslak kaydeder, **göndermez**)
- "Taslağı gönder." (önce okur, sonra onay penceresi açar)

**Telegram**
- "Telegram'da yeni mesaj var mı?"
- "Telegram'dan bana 'eve geldim' yaz."
- Telefondan bota mesaj at: JARVIS sesli bildirir ve sohbet izinliyse otomatik cevap verir.

**Ulaşım**
- "5 numaralı otobüs ne zaman kalkıyor?"
- "Konak'ta hangi duraklar var?"
- "Bornova'dan Konak'a nasıl giderim?" (Google Haritalar açılır)
- "İzmirim Kart bakiyeme bak."

**Ajanlar**
- "Ulaşım ajanına sor: yarın 9'da Üçkuyular'dan Konak'a nasıl giderim?"
- "Sekreter maillerimi özetleyip bana Telegram'dan atsın."

---

## Modelleri değiştirmek

Bütün model seçimleri `agents/agents.json` dosyasında. Kodu değiştirmen gerekmez, dosyayı düzenleyip JARVIS'i yeniden başlatman yeterli.

```jsonc
// Bir ajanın modeli
{ "name": "kodcu", "model": "claude-opus-5-5", "fallback_model": "qwen/qwen3.8-27b:free", "effort": "high", ... }

// Hangi ajanın çalışacağına karar veren yönlendirici
"orchestrator": { "default_model": "openrouter/free", "fallback_models": ["google/gemini-3.5-flash-lite"] }

// Eklentiler (ajan olmayan yan kollar)
"channels": {
  "telegram":    { "model": "openrouter/free", "fallback_models": ["google/gemini-3.5-flash-lite"] },
  "gmail_draft": { "model": "anthropic/claude-sonnet-5.5", "fallback_models": ["openrouter/free"] }
}
```

- Model adlarını https://openrouter.ai/models adresinden kopyala. Sonu `:free` olanlar ücretsizdir.
- `gemini-flash-lite-latest` gibi `/` içermeyen adlar doğrudan Gemini'ye gider.
- `claude-` ile başlayan adlar doğrudan Claude'a (Anthropic API) gider; `.env`'de `ANTHROPIC_API_KEY` gerekir. `effort` (low/medium/high/xhigh/max) ne kadar derin düşüneceğini belirler.
- **Dikkat:** Claude **ücretlidir**. Anthropic hesabında bakiye yoksa bu adım atlanır ve sıradaki yedeğe geçilir.

---

## Sorun giderme

| Belirti | Sebep | Çözüm |
|---|---|---|
| Log'da `YEDEK MODELE GECILIYOR` | Model adı yanlış ya da kotası dolu | Model adını openrouter.ai/models'ta kontrol et |
| `OpenRouter (ANAHTAR YOK -> Gemini)` | `OPENROUTER_API_KEY` boş | Adım 2 |
| `Gmail token gecersiz` | Token silinmiş ya da izin geri alınmış | `python scripts/gmail_auth.py` |
| `Gmail OAuth yapilandirilmamis` | `config/gmail_credentials.json` yok | Adım 4.1 |
| `Spotify yapilandirilmamis` | `.env` anahtarı ya da token yok | Adım 5b |
| Spotify `403` / Premium hatası | Hesap Premium değil | Oynatma kontrolü Premium ister |
| `Calacak Spotify cihazi yok` | Spotify hiçbir cihazda açık değil | Uygulamayı aç ya da `device` belirt |
| Telegram `409 Conflict` | Bot başka bir yerde de dinleniyor | Diğer programı kapat |
| Bot cevap vermiyor ama JARVIS bildiriyor | Sohbet izinli listede değil | `TELEGRAM_ALLOWED_CHAT_IDS`'e ekle |
| Canlı otobüste `IZMIR_OPENAPI_TOKEN` hatası | Canlı servis token istiyor | Token ekle ya da hat saatlerini kullan |
| ESHOT verisi indirilemedi | İnternet yok | Bağlantıyı kontrol et; eski veri varsa o kullanılır |

Her şeyin yerinde olup olmadığını testlerle kontrol edebilirsin:
```bash
python -m pytest tests -q --ignore=tests/test_keyboard_live.py
```

---

## Güvenlik notları

- `.env`, `config/gmail_credentials.json` ve `data/` klasörü (Gmail token'ı dahil) **git'e eklenmez**. Bunları kimseyle paylaşma.
- Ajanlar **e-posta gönderemez**, sadece taslak hazırlayabilir. Telegram'da da yalnızca sana bildirim atabilirler.
- Sesle istenen bütün e-posta ve Telegram gönderimleri **onay penceresinden** geçer.
- Telegram otomatik yanıtı yalnızca izin verdiğin sohbetlere gider ve JARVIS kendisine sorulursa yapay zekâ olduğunu saklamaz.
- MCP ile yapılan yazma/silme işlemleri sesli JARVIS'de **onay penceresinden** geçer; tarayıcı ajanı kart ve şifre alanlarına dokunmaz.
