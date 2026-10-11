# Harici Ajan Koprusu

Bu klasor beyin motoru ile harici otonom ajanlar arasindaki dosya tabanli mesajlasma kanalidir.

## `outbox.txt` (ajanlar -> beyin)
Harici ajanlar bu dosyaya **satir satir** (her mesaj bir satir) yazar.
`bridge_listener.py` dosyayi `tail -f` mantigiyla izler ve yeni her satiri
`session.send_client_content` ile canli Gemini oturumuna enjekte eder.

- Beyin acildiginda dosyadaki mevcut birikim ATLANIR; sadece yeni satirlar islenir.
- Dosya kirpilirsa/silinirse okuma offseti sifirlanir.

Ornek:
```
Kullanicinin takviminde 15:00'te toplanti var, hatirlat.
Derleme tamamlandi, testler gecti.
```

## `inbox.txt` (beyin -> ajanlar)
`dispatch_to_agent` araci cagrildiginda beyin bu dosyaya JSON satiri ekler:
```json
{"agent": "arastirmaci", "task": "X konusunu ozetle", "ts": "2026-09-02T12:00:00+03:00"}
```
Harici ajan orkestratoru bu dosyayi izleyip gorevleri dagitir.
