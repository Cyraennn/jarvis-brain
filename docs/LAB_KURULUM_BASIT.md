JARVIS'İ LAB BİLGİSAYARINA KURMA - ADIM ADIM (BASİT ANLATIM)
================================================================

Bu dosyayı LAB BİLGİSAYARINDA okuyorsun (USB'yi oraya taktıktan sonra).
Aşağıdaki adımları SIRAYLA yap, hiçbirini atlama. Toplam süre: ~20-30 dakika.

Neye ihtiyacın var:
  - Bu USB (içinde bir zip dosyası var: jarvis-lab-package-....zip)
  - İnternet bağlantısı
  - Yönetici (admin) yetkisi (zaten var, kendine söylemiştin)

================================================================
ADIM 1: Dosyaları bilgisayara kopyala
================================================================
1. "Bu Bilgisayar" penceresini aç.
2. C: diskine git.
3. Bos bir yerde sag tikla > Yeni > Klasor, adini "JARVIS" koy.
   Simdi elinde "C:\JARVIS" diye bos bir klasor var.
4. USB'deki zip dosyasini (jarvis-lab-package-....zip) bu C:\JARVIS
   klasorunun ICINE kopyala (surukle-birak yeterli).
5. Kopyaladigin zip dosyasina sag tikla, "Tumunu Ayikla..." (Extract All) de.
6. Cikan pencerede yolun "C:\JARVIS" oldugundan emin ol, "Ayikla" (Extract) de.
7. Bittiginde C:\JARVIS klasorunun icinde "jarvis-brain" ve
   "JARVIS-Hafiza-Vault" adinda IKI klasor OLMALI. Yoksa zip'i yanlis yere
   acmissindir, sil ve tekrar dene.
8. (Artik zip dosyasinin kendisini silebilirsin, isin bitti onunla.)

================================================================
ADIM 2: Python programini kur (JARVIS'in calismasi icin sart)
================================================================
1. Tarayiciyi ac (Chrome/Edge fark etmez).
2. Adres cubuguna yaz: python.org/downloads
3. "Download Python 3.xx" butonuna bas, indir.
4. Indirilen dosyaya cift tikla, kurulum baslar.
5. COK ONEMLI: Kurulum ekraninin EN ALTINDA "Add python.exe to PATH" diye
   bir kutucuk var - ONU ISARETLE (tik at). Sonra "Install Now" de.
6. Kurulum bitince pencereyi kapat.

================================================================
ADIM 3: Tailscale programini kur (iki bilgisayari birbirine baglar)
================================================================
1. Tarayicida yaz: tailscale.com/download
2. Windows icin indir, calistir, "Install" de.
3. Kurulum bitince ekranin sag alt kosesinde (saatin yaninda) kucuk bir
   Tailscale ikonu cikar.
4. O ikona tikla, "Log in" / "Giris yap" de.
   *** EV BILGISAYARINDA GIRIS YAPTIGIN AYNI HESAPLA (orn. Google hesabi)
   giris yap - farkli hesap kullanirsan iki bilgisayar birbirini GOREMEZ. ***
5. Giris yaptiktan sonra ikon "Connected" (bagli) demeli.
6. SIMDI BU BILGISAYARIN ADINI OGREN: ikona tikla, acilan listede en ustte
   bir bilgisayar ismi gorursun (ornek: "DESKTOP-AB12CD" veya sonu
   ".ts.net" ile biten uzun bir isim). BU ISMI BIR KAGIDA YAZ - birazdan
   lazim olacak (ADIM 7'de).

================================================================
ADIM 4: JARVIS'in ihtiyac duydugu ek programlari kur
================================================================
1. Baslat menusune tikla, "cmd" yaz, cikan "Komut Istemi" (Command Prompt)
   programina tikla. Siyah bir pencere acilir, korkma, normal.
2. Bu pencereye su satiri yaz (veya kopyala-yapistir) ve Enter'a bas:

     cd C:\JARVIS\jarvis-brain

3. Sonra su satiri yaz, Enter'a bas (biraz surebilir, bekle):

     python -m venv .venv

4. Sonra su satiri yaz, Enter'a bas:

     .venv\Scripts\activate

   (satirin basinda "(.venv)" yazisi cikarsa dogru gitmissin demektir)
5. Sonra su satiri yaz, Enter'a bas (BU ADIM birkac dakika surebilir,
   internetten indirir, pencereyi KAPATMA, bitmesini bekle):

     pip install -r requirements.txt

================================================================
ADIM 5: Ayar dosyasinin adini degistir
================================================================
1. Dosya gezgininde C:\JARVIS\jarvis-brain klasorune git.
2. ".env.for-lab" adinda bir dosya goreceksin.
   (Gorunmuyorsa: yukarida "Gorunum" (View) > "Gizli Ogeler"
   (Hidden items) kutucugunu isaretle.)
3. Bu dosyaya sag tikla > "Yeniden Adlandir" (Rename).
4. Adini TAM OLARAK ".env" yap (basinda nokta var, sonunda hicbir
   sey yok - "for-lab" kismini tamamen sil). Enter'a bas.
   (Windows "uzanti degisecek, emin misin" diye sorabilir - "Evet" de.)

================================================================
ADIM 6: JARVIS'i calistir
================================================================
1. ADIM 4'teki siyah pencereye (Komut Istemi) geri don.
   (Kapattiysan: ADIM 4.1'den 4.4'e kadar tekrar yap.)
2. Su satiri yaz, Enter'a bas:

     python run_server.py

3. Ekranda bir suru renkli yazi akacak. Sunlari GORMELISIN:
     - "Web konsolu: http://..." yazan bir satir
     - "Uzak ses sunucusu dinliyor" yazan bir satir
   Bunlari goruyorsan JARVIS CALISIYOR demektir. TEBRIKLER.
4. BU PENCEREYI KAPATMA. Kapatirsan JARVIS durur. Bilgisayari kapatmadan,
   pencereyi de kapatmadan oyle birak (uyku moduna gecmesin diye Windows
   ayarlarindan "Uyku"yu da kapatman iyi olur).

================================================================
SIMDI EV BILGISAYARINA DON
================================================================
Ev bilgisayarinda "remote_client" klasorundeki ".env" dosyasini ac (Not
Defteri ile), "JARVIS_SERVER_HOST=" yazan satirin sonuna, ADIM 3.6'da
kagida yazdigin ismi ekle, kaydet. Sonra "python run_remote_client.py"
ile baslat. Artik JARVIS'le konusabilirsin.

================================================================
BIR SEY TERS Mi GITTI? (sik karsilasilan sorunlar)
================================================================
- "python komutu taninmiyor / not recognized" hatasi: ADIM 2'yi tekrar
  yap, "Add python.exe to PATH" kutusunu isaretlemeyi unutmussundur.
  Bilgisayari yeniden baslat, tekrar dene.
- Ilk calistirmada Windows bir "Guvenlik Duvari izni" penceresi acabilir
  (Windows Defender Firewall) - "Izin Ver" (Allow access) de, yoksa ev
  bilgisayari baglanamaz.
- Siyah pencerede kirmizi "APIError" / "API key not valid" yazisi:
  internet/anahtar sorunu olabilir - ekran goruntusu al, gonder, bakalim.
- "Web konsolu" satiri hic cikmadi: ADIM 5 dogru yapilmamis olabilir,
  ".env" dosyasinin TAM ADINI kontrol et (".env.for-lab" DEGIL, ".env").

Takildigin her yerde ekran goruntusu al, ne yaptigini anlat - birlikte
cozeriz. Detayli (teknik) versiyon icin: docs/remote_setup.md
