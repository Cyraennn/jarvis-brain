# CYRAEN'i VPS'e kurma (sunucu = beyin, PC = gövde)

```
   EV PC (istemci)                      Tailscale (şifreli VPN)            VPS - Ubuntu 24.04 (sunucu)
┌──────────────────────────┐                                         ┌───────────────────────────────┐
│ python -m client --ui    │◄──── ws  :8765/ws  (komut/olay/eylem) ──►│ python -m server  (systemd)   │
│  - HUD arayüzü           │◄──── ws  :8771     (mikrofon/hoparlör) ─►│  - Gemini Live (canlı beyin)  │
│  - klavye/fare/uygulama  │                                         │  - 27 ajan + Conductor        │
│  - ekran/kamera karesi   │◄──── http :8770    (web konsolu/okul) ──►│  - hatırlatıcı/rutin          │
│  - ADB (telefon)         │                                         │  - GBrain + Obsidian hafıza   │
│  - onay pencereleri      │                                         │  - e-posta (onaylı gönderme)  │
└──────────────────────────┘                                         └───────────────────────────────┘
```

- İnternete **hiçbir port açılmaz**. Sunucu yalnızca Tailscale IP'sine bağlanır; `ufw` gelen her şeyi reddeder (SSH ve Tailscale hariç).
- Masaüstü işleri (uygulama açma, yazma, dosya, ekran, telefon) **sunucuda asla yapılmaz**. Sunucu, bağlı PC'ye "eylem isteği" gönderir. PC kapalıysa CYRAEN bunu açıkça söyler.
- Riskli işlemler **sunucuda onaya bağlıdır**: e-posta gönderme, süreç kapatma, kod çalıştırma, uygulama kapatma ve "İnsan Onaylı" ajanlar. Onay PC'de pencere olarak çıkar. 120 sn içinde cevap gelmezse işlem **reddedilir**.

---

## 1. VPS oluştur

- Herhangi bir sağlayıcıyı kullanabilirsin (Hetzner, DigitalOcean, Contabo…). **Ubuntu 24.04**, en az **2 vCPU / 2 GB RAM / 20 GB disk**.
- GPU gerekmez: tüm modeller API tabanlı (Gemini).
- Oluştururken **SSH anahtarını** ekle (şifreyle kurma). Anahtarın yoksa PC'de PowerShell'de üret:
  ```powershell
  ssh-keygen -t ed25519 -C "cyraen-vps"
  Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub     # bunu sağlayıcının panelindeki "SSH key" alanına yapıştır
  ```

## 2. SSH anahtarıyla gir, yönetici kullanıcı oluştur

```bash
ssh root@<VPS_IP>

adduser kullanici                                  # kendi yönetici kullanıcın
usermod -aG sudo kullanici
mkdir -p /home/kullanici/.ssh && cp ~/.ssh/authorized_keys /home/kullanici/.ssh/
chown -R kullanici:kullanici /home/kullanici/.ssh && chmod 700 /home/kullanici/.ssh && chmod 600 /home/kullanici/.ssh/authorized_keys
```

**Yeni bir terminalde** `ssh kullanici@<VPS_IP>` ile girebildiğini doğrula. Sonra bir sonraki adıma geç.

## 3. Şifreli girişi kapat

```bash
sudo tee /etc/ssh/sshd_config.d/99-cyraen.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t && sudo systemctl restart ssh
```

> ⚠️ Mevcut oturumu **kapatmadan** yeni bir terminalden `ssh kullanici@<VPS_IP>` dene. Girebiliyorsan tamam.

## 4. Tailscale (sunucu + PC)

**Sunucu:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                      # çıkan linki tarayıcıda aç, hesabınla onayla
tailscale ip -4                        # örn. 100.101.102.103
```

**PC:** https://tailscale.com/download adresinden Windows uygulamasını kur ve **aynı hesapla** giriş yap. Sonra kontrol et:
```powershell
tailscale status                       # VPS listede görünmeli (örn. "cyraen-vps")
ping cyraen-vps
```

> İsteğe bağlı: Tailscale yönetim panelinde VPS için **"Disable key expiry"** seçeneğini aç. Aksi halde 180 günde bir yeniden giriş ister.

## 5. Kodu sunucuya yükle

Depo henüz git'te değil. PC'de PowerShell'de, **sırlar ve yerel veri hariç** bir arşiv oluştur:
```powershell
cd "C:\Users\KULLANICI\OneDrive\Masaüstü\Masaüstü\multi"
tar -czf cyraen.tgz --exclude=cyraen-brain/.env --exclude=cyraen-brain/client/.env `
    --exclude=cyraen-brain/data --exclude=cyraen-brain/.venv --exclude="__pycache__" `
    --exclude=cyraen-brain/build --exclude=cyraen-brain/dist cyraen-brain
scp cyraen.tgz kullanici@cyraen-vps:/tmp/
```
Sunucuda:
```bash
sudo mkdir -p /opt/cyraen && sudo tar -xzf /tmp/cyraen.tgz -C /opt/cyraen && rm /tmp/cyraen.tgz
ls /opt/cyraen/cyraen-brain/server      # __main__.py görünmeli
```

## 6. Kurulum betiği

```bash
sudo bash /opt/cyraen/cyraen-brain/deploy/setup.sh
```
Betik şunları yapar:
- venv ve bağımlılıkları kurar;
- `cyraen` servis kullanıcısını oluşturur (root değil);
- `.env`'i oluşturur ve **CYRAEN_TOKEN'ı üretir**;
- sunucuyu Tailscale IP'sine bağlar;
- ufw'yi açar (varsayılan red; yalnızca SSH ve tailscale0);
- systemd servisini kurar.

Tekrar çalıştırmak güvenlidir.

## 7. `.env`'i doldur

```bash
sudo nano /opt/cyraen/cyraen-brain/.env
```
- **`GEMINI_API_KEY=`** zorunlu.
- `TELEGRAM_BOT_TOKEN=` ve `TELEGRAM_CHAT_ID=` isteğe bağlı; kritik hata bildirimi için. Nasıl alınacağı dosyadaki yorumda yazıyor.
- `EMAIL_ADDRESS=` ve `EMAIL_APP_PASSWORD=` e-posta için.
- Token'ı PC'ye aktarmak için göster:
  ```bash
  sudo grep ^CYRAEN_TOKEN= /opt/cyraen/cyraen-brain/.env
  ```

## 8. Hafızayı PC'den sunucuya taşı

GBrain, hatırlatıcılar, rutinler, okul durumu, konuşma kayıtları ve Obsidian kasası taşınacak. **Taşımadan önce PC'de CYRAEN'i kapat** (tepsiden Çıkış). Yoksa iki kopya birbirinden ayrışır.

PC (PowerShell):
```powershell
cd "C:\Users\KULLANICI\OneDrive\Masaüstü\Masaüstü\multi\cyraen-brain"
tar -czf hafiza.tgz data "C:\Users\KULLANICI\Documents\JARVIS Hafiza"
scp hafiza.tgz kullanici@cyraen-vps:/tmp/
```
Sunucu:
```bash
cd /tmp && tar -xzf hafiza.tgz
sudo rsync -a /tmp/data/ /opt/cyraen/cyraen-brain/data/
sudo rsync -a "/tmp/Users/KULLANICI/Documents/JARVIS Hafiza/" /opt/cyraen/hafiza/
sudo rm -rf /tmp/data /tmp/Users /tmp/hafiza.tgz
sudo chown -R cyraen:cyraen /opt/cyraen
```
- `data/whatsapp_session/` gereksiz: WhatsApp sunucuda çalışmaz; silebilirsin.
- **Obsidian'ı PC'de görmek istersen:** Syncthing ile `/opt/cyraen/hafiza` ↔ PC klasörünü eşitleyebilirsin (Tailscale üzerinden). Yalnızca **okumak** için kullan; yazan taraf sunucu olmalı.
- **Okul uygulaması:** `okul/assets/js/config.js` içindeki `cyraen.host` değerini `localhost` yerine VPS'in Tailscale adı yap (`cyraen-vps`). `token` değeri CYRAEN_TOKEN (ya da ayrı verdiysen CYRAEN_WEB_TOKEN) olmalı.

## 9. Servisi başlat ve izle

```bash
sudo systemctl restart cyraen
sudo systemctl status cyraen
journalctl -u cyraen -f                        # canlı log (Ctrl+C ile çık)
```
Açılışta **her model gerçek bir istekle test edilir**. Loglarda şunlar görünür:
- `Model testi OK: ...` ya da `Model testi BASARISIZ: ...`
- Birincil model çalışmıyorsa: `Ajanlar YEDEK model ... ile calisacak`

Bunlar ayrıca Telegram'a da düşer.

JSON log dosyası (10 MB'ta döner, 10 dosya saklanır):
```bash
sudo tail -f /opt/cyraen/cyraen-brain/data/logs/server.jsonl
# yalnızca yedek model geçişleri:
sudo grep '"model_fallback"' /opt/cyraen/cyraen-brain/data/logs/server.jsonl
```

## 10. PC istemcisini bağla

```powershell
cd "C:\Users\KULLANICI\OneDrive\Masaüstü\Masaüstü\multi\cyraen-brain"
copy client\.env.example client\.env
notepad client\.env          # CYRAEN_SERVER_HOST=cyraen-vps ve CYRAEN_TOKEN=<sunucudaki değer>

python -m client --ui        # sinematik HUD, sunucuya bağlı
# ya da arayüzsüz:
python -m client
```
Artık **`python run_ui.py` kullanma**. O komut CYRAEN'i PC'de yerel olarak çalıştırır ve sunucudan ayrı bir hafıza kullanır.

---

## Test komutları

Değişkenler (PC, PowerShell):
```powershell
$T = "<CYRAEN_TOKEN>"
$S = "http://cyraen-vps:8765"
```

**Sağlık:**
```powershell
curl.exe -s -H "X-Token: $T" "$S/health"
curl.exe -s -H "X-Token: $T" "$S/health?probe=1"      # modelleri şimdi yeniden test et
curl.exe -s -o NUL -w "%{http_code}" "$S/health"       # token'sız -> 401 olmalı
```

**Komut:**
```powershell
Invoke-RestMethod -Method Post -Uri "$S/command" -Headers @{ "X-Token" = $T } `
  -ContentType "application/json; charset=utf-8" -Body '{"text":"Saat kaç?"}'
```
Linux/macOS (curl):
```bash
curl -s -X POST -H "X-Token: $T" -H "Content-Type: application/json" \
     -d '{"text":"Saat kaç?"}' http://cyraen-vps:8765/command
```
Örnek cevap:
```json
{"ok":true,"text":"Saat 22.31.","model":"gemini-2.5-flash-native-audio-latest",
 "fallback":false,"error":null,"warnings":[],"elapsed_ms":2400,"tools":["get_current_datetime"]}
```
- **503:** canlı oturum bağlı değil (`/health`'e bak).
- **401:** token yanlış.

**WebSocket** ([websocat](https://github.com/vi/websocat/releases)):
```bash
websocat ws://cyraen-vps:8765/ws
{"type":"auth","token":"<CYRAEN_TOKEN>","client":{"name":"deneme","kind":"cli","actions":[]}}
{"type":"command","id":"1","text":"Merhaba CYRAEN"}
{"type":"ping"}
```
Bağlanınca önce `hello` gelir, ardından `snapshot` ve canlı `event` akışı (transkript, durum, görev). Son olarak `command_result` gelir.

**Eylem köprüsü:**
1. PC'de istemci çalışırken "Not Defteri'ni aç" de; PC'de açılmalı.
2. İstemciyi kapatıp aynı komutu ver; CYRAEN "bağlı istemci yok" demeli.
3. Sunucu logunda `Eylem istegi -> ev-pc: open_application` satırı görünmeli.

**Onay:** "Chrome sürecini kapat" de.
1. PC'de onay penceresi çıkmalı.
2. **Hayır** dersen hiçbir şey kapanmamalı.
3. Cevap vermeden 120 sn beklersen işlem reddedilmeli.

---

## Güncelleme

PC'de 5. adımdaki `tar` + `scp` komutlarıyla yeni `cyraen.tgz` gönder. Sonra sunucuda:
```bash
sudo systemctl stop cyraen
sudo tar -xzf /tmp/cyraen.tgz -C /opt/cyraen          # .env ve data/ arşivde yok -> korunur
sudo /opt/cyraen/venv/bin/pip install -q -r /opt/cyraen/cyraen-brain/requirements-server.txt
sudo chown -R cyraen:cyraen /opt/cyraen
sudo systemctl start cyraen && journalctl -u cyraen -f
```
(Depo git'e alındığında bu adım `git pull` olur.)

## Sorun giderme

| Belirti | Neden / çözüm |
|---|---|
| `systemctl status` sürekli `activating (auto-restart)` | `journalctl -u cyraen -n 50`. Genelde `.env` eksiktir (GEMINI_API_KEY, CYRAEN_TOKEN) ya da Tailscale IP'si henüz hazır değildir; servis 5 sn'de bir yeniden dener. |
| `CYRAEN_SERVER_BIND='0.0.0.0' reddedildi` | Bilinçli. Tailscale IP'sini yaz (`tailscale ip -4`) ya da `127.0.0.1`. |
| PC istemcisi `baglanti yok/koptu` diyip tekrar deniyor | `ping cyraen-vps` ve `tailscale status` ile kontrol et. İstemci 1-2-4-…-30 sn aralıklarla kendiliğinden yeniden bağlanır. |
| `Sunucu kimligi reddetti` | `client/.env` CYRAEN_TOKEN ile sunucudaki aynı değil. |
| Ses yok ama komutlar çalışıyor | Ses kanalı 8771'de. Aynı anda tek ses istemcisi bağlanabilir (başka istemci açıksa 409). |
| `/health` → `model_problems` dolu | İlgili model erişilemez. Mesajda hangi yedeğin kullanılacağı yazar. Telegram'a da bildirilir. |
| Telegram'a "Canlı oturum ... BAĞLI DEĞİL" geldi | Oturum 5 dk'dır kopuk. Sebep API anahtarı, kota ya da ağ olabilir. `journalctl -u cyraen` içinde `Oturum hatasi` satırına bak. Oturum düzelince bir kez "yeniden BAĞLANDI" bildirimi gelir. |
