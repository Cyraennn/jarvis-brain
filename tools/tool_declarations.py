"""Gemini Live icin Function Declaration tanimlari.

Buradaki her tanim `tools/tool_runner.py` icindeki bir implementasyona karsilik gelir.
"""

from __future__ import annotations

from google.genai import types

_STR = types.Type.STRING
_INT = types.Type.INTEGER
_NUM = types.Type.NUMBER
_BOOL = types.Type.BOOLEAN
_OBJ = types.Type.OBJECT


def _obj(properties: dict[str, types.Schema], required: list[str] | None = None) -> types.Schema:
    return types.Schema(type=_OBJ, properties=properties, required=required or [])


def build_declarations(disabled: "set[str] | frozenset[str] | None" = None) -> list[types.FunctionDeclaration]:
    """Modele verilecek araclar. `disabled`: kapatilan grup adlari (bkz. TOOL_GROUPS, env JARVIS_TOOLS_OFF)."""
    off = set(disabled or ())
    return [*_core_declarations(), *(d for g, fn in TOOL_GROUPS.items() if g not in off for d in fn())]


def _core_declarations() -> list[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name="get_current_datetime",
            description="Gecerli tarih ve saati yerel saat dilimiyle dondurur.",
        ),
        types.FunctionDeclaration(
            name="get_system_status",
            description=(
                "Uzerinde calistigi bilgisayarin isletim sistemi, islemci ve "
                "Python surum bilgisini verir."
            ),
        ),
        types.FunctionDeclaration(
            name="list_directory",
            description="Verilen dizindeki dosya ve klasorleri listeler.",
            parameters=_obj(
                {"path": types.Schema(type=_STR, description="Listelenecek dizin yolu")},
                ["path"],
            ),
        ),
        types.FunctionDeclaration(
            name="read_text_file",
            description="Bir metin dosyasinin icerigini okur (karakter sinirina kadar).",
            parameters=_obj(
                {
                    "path": types.Schema(type=_STR, description="Okunacak dosyanin yolu"),
                    "max_chars": types.Schema(
                        type=_INT,
                        description="En fazla kac karakter okunacagi (varsayilan 4000)",
                    ),
                },
                ["path"],
            ),
        ),
        types.FunctionDeclaration(
            name="write_text_file",
            description="Bir metin dosyasina yazar (append=true ise sonuna ekler).",
            parameters=_obj(
                {
                    "path": types.Schema(type=_STR, description="Yazilacak dosya yolu"),
                    "content": types.Schema(type=_STR, description="Dosya icerigi"),
                    "append": types.Schema(type=_BOOL, description="Sona ekle (varsayilan false)"),
                },
                ["path", "content"],
            ),
        ),
        types.FunctionDeclaration(
            name="remember_note",
            description=(
                "Kalici hafizaya zaman damgali bir not ekler. Obsidian vault "
                "tanimliysa not <vault>/JARVIS/Notlar/ altina da yazilir."
            ),
            parameters=_obj(
                {"content": types.Schema(type=_STR, description="Hatirlanacak not metni")},
                ["content"],
            ),
        ),
        types.FunctionDeclaration(
            name="recall_notes",
            description="Daha once kaydedilmis notlari (en fazla son 50) getirir.",
        ),
        types.FunctionDeclaration(
            name="dispatch_to_agent",
            description=(
                "Bir gorevi FounderOS cok-ajanli sistemine (6 departman, 37 ajan) "
                "iletir. `agent` verilmezse ('auto') JARVIS Conductor gorevi analiz "
                "edip en uygun departman + alt ajana delege eder. Departmanlar: TECH "
                "(kod/markdown/sistem/API), COMMUNICATIONS (mesaj/e-posta/duyuru), "
                "SALES (musteri bulma/teklif), FINANCES (gelir/gider/fatura), CLIENTS "
                "(onboarding/destek/geri bildirim), MARKETING (icerik/SEO/analitik). "
                "Sonuc kopru uzerinden birkac saniyede geri gelir. Bazi ajanlar insan "
                "onayi gerektirir (kullaniciya soyle)."
            ),
            parameters=_obj(
                {
                    "task": types.Schema(type=_STR, description="Ajana verilecek gorev tanimi"),
                    "agent": types.Schema(
                        type=_STR,
                        description="Belirli bir ajan kod adi (orn. sinav_kocu, arastirmaci, markdown_denetcisi) veya 'auto'",
                    ),
                },
                ["task"],
            ),
        ),
        types.FunctionDeclaration(
            name="open_application",
            description=(
                "Bilgisayarda adiyla bir masaustu uygulamasi acar "
                "(orn. 'chrome', 'spotify', 'not defteri', 'vscode', 'steam'). "
                "Varsayilan olarak Windows arama cubugunu acip uygulama adini "
                "harf harf yazar ve Enter'lar."
            ),
            parameters=_obj(
                {"name": types.Schema(type=_STR, description="Acilacak uygulamanin adi")},
                ["name"],
            ),
        ),
        types.FunctionDeclaration(
            name="type_in_search",
            description=(
                "Windows arama cubugunu (Win+S) acar ve verilen metni harf harf "
                "yazar. submit=true ise Enter'a basip ilk sonucu acar. Kullanici "
                "'arama cubuguna ... yaz' derse veya bir seyi arama uzerinden "
                "actirmak isterse kullan."
            ),
            parameters=_obj(
                {
                    "text": types.Schema(type=_STR, description="Arama cubuguna yazilacak metin"),
                    "submit": types.Schema(
                        type=_BOOL, description="Yazdiktan sonra Enter'a basilsin mi (varsayilan true)"
                    ),
                },
                ["text"],
            ),
        ),
        types.FunctionDeclaration(
            name="type_text",
            description=(
                "Metni HARF HARF yazar. EN GUVENILIR kullanim: once look_at_screen "
                "ile ekrani gor, yazi yazilacak alani (metin editoru govdesi, form "
                "kutusu...) 0-1000 normalize koordinatla belirle ve x,y ver -> arac "
                "once oraya tiklar sonra yazar. Alternatif: basit tek-alanli "
                "uygulamalar icin app='not defteri' (uygulama acik olmali). Hicbiri "
                "verilmezse odaktaki yere yazar. Cok satir icin metne \\n koy."
            ),
            parameters=_obj(
                {
                    "text": types.Schema(type=_STR, description="Yazilacak metin"),
                    "x": types.Schema(
                        type=_NUM, description="Yazmadan once tiklanacak nokta - yatay 0-1000"
                    ),
                    "y": types.Schema(
                        type=_NUM, description="Yazmadan once tiklanacak nokta - dikey 0-1000"
                    ),
                    "app": types.Schema(
                        type=_STR, description="Basit tek-alanli hedef uygulama adi (x,y yoksa)"
                    ),
                    "submit": types.Schema(
                        type=_BOOL, description="Sonda Enter'a basilsin mi (varsayilan false)"
                    ),
                },
                ["text"],
            ),
        ),
        types.FunctionDeclaration(
            name="click_at",
            description=(
                "Ekranda bir noktaya fare ile tiklar. Koordinatlar 0-1000 NORMALIZE "
                "(x = soldan yatay, y = yukaridan dikey). Once look_at_screen ile "
                "ekrani gor, yaziyi/tiklamayi yapacagin alani belirle, buraya tikla, "
                "sonra type_text (app olmadan) ile yaz. Yanlis yere yazma sorununda "
                "bu akisi kullan."
            ),
            parameters=_obj(
                {
                    "x": types.Schema(type=_NUM, description="Yatay konum 0-1000 (soldan)"),
                    "y": types.Schema(type=_NUM, description="Dikey konum 0-1000 (yukaridan)"),
                    "button": types.Schema(type=_STR, description="left | right | middle (varsayilan left)"),
                    "double": types.Schema(type=_BOOL, description="Cift tiklama (varsayilan false)"),
                },
                ["x", "y"],
            ),
        ),
        types.FunctionDeclaration(
            name="clear_field",
            description=(
                "Verilen noktadaki giris alanini TUMUYLE temizler (tikla -> Ctrl+A "
                "-> Delete). Kullanici 'sunu sil', 'bu kutuyu temizle' dediginde, "
                "tek bir alan icin bunu kullan. Once look_at_screen ile alani gor."
            ),
            parameters=_obj(
                {
                    "x": types.Schema(type=_NUM, description="Yatay 0-1000"),
                    "y": types.Schema(type=_NUM, description="Dikey 0-1000"),
                },
                ["x", "y"],
            ),
        ),
        types.FunctionDeclaration(
            name="drag_select",
            description=(
                "Iki nokta arasindaki metni fare ile surukleyerek secer. Secimden "
                "sonra press_keys('delete') ile sil veya type_text ile ustune yaz. "
                "Bir metin parcasini/cumleyi silmek icin kullan. Koordinatlar 0-1000."
            ),
            parameters=_obj(
                {
                    "start_x": types.Schema(type=_NUM, description="Baslangic yatay 0-1000"),
                    "start_y": types.Schema(type=_NUM, description="Baslangic dikey 0-1000"),
                    "end_x": types.Schema(type=_NUM, description="Bitis yatay 0-1000"),
                    "end_y": types.Schema(type=_NUM, description="Bitis dikey 0-1000"),
                },
                ["start_x", "start_y", "end_x", "end_y"],
            ),
        ),
        types.FunctionDeclaration(
            name="select_word",
            description="Bir noktadaki kelimeyi cift tiklayarak secer (sonra sil/degistir).",
            parameters=_obj(
                {
                    "x": types.Schema(type=_NUM, description="Yatay 0-1000"),
                    "y": types.Schema(type=_NUM, description="Dikey 0-1000"),
                },
                ["x", "y"],
            ),
        ),
        types.FunctionDeclaration(
            name="select_line",
            description="Bir noktadaki satiri/paragrafi uc tiklayarak secer.",
            parameters=_obj(
                {
                    "x": types.Schema(type=_NUM, description="Yatay 0-1000"),
                    "y": types.Schema(type=_NUM, description="Dikey 0-1000"),
                },
                ["x", "y"],
            ),
        ),
        types.FunctionDeclaration(
            name="erase_chars",
            description=(
                "Imlecin bulundugu yerden karakter siler. forward=false => geriye "
                "(Backspace), true => ileriye (Delete)."
            ),
            parameters=_obj(
                {
                    "count": types.Schema(type=_INT, description="Silinecek karakter sayisi"),
                    "forward": types.Schema(type=_BOOL, description="Ileri yonde sil (varsayilan false)"),
                },
                ["count"],
            ),
        ),
        types.FunctionDeclaration(
            name="press_keys",
            description=(
                "Klavye kisayolu / ozel tus gonderir. Orn: 'enter', 'tab', 'ctrl+s', "
                "'ctrl+a', 'ctrl+shift+n'. Alan degistirmek icin 'tab', "
                "onaylamak icin 'enter'. Pencere/sekme KAPATMAK icin bunu kullanma "
                "(alt+f4, ctrl+w o an odakta ne varsa onu kapatir): close_application "
                "ya da close_active_tab kullan."
            ),
            parameters=_obj(
                {"keys": types.Schema(type=_STR, description="Tus dizisi, orn. 'ctrl+s'")},
                ["keys"],
            ),
        ),
        types.FunctionDeclaration(
            name="scroll",
            description="Fare tekerini kaydirir. Pozitif = yukari, negatif = asagi (adim).",
            parameters=_obj(
                {"amount": types.Schema(type=_INT, description="Kaydirma miktari, orn. -3")},
                ["amount"],
            ),
        ),
        types.FunctionDeclaration(
            name="move_mouse",
            description="Fare imlecini 0-1000 normalize bir noktaya tasir (tiklamadan).",
            parameters=_obj(
                {
                    "x": types.Schema(type=_NUM, description="Yatay 0-1000"),
                    "y": types.Schema(type=_NUM, description="Dikey 0-1000"),
                },
                ["x", "y"],
            ),
        ),
        types.FunctionDeclaration(
            name="type_in_browser",
            description=(
                "Varsayilan tarayiciyi acar ve adres/arama cubuguna verilen metni "
                "HARF HARF yazar; submit=true ise Enter'lar. URL, alan adi veya "
                "arama sorgusu kabul eder."
            ),
            parameters=_obj(
                {
                    "text": types.Schema(type=_STR, description="Tarayiciya yazilacak URL veya arama metni"),
                    "submit": types.Schema(type=_BOOL, description="Enter'a basilsin mi (varsayilan true)"),
                },
                ["text"],
            ),
        ),
        types.FunctionDeclaration(
            name="close_application",
            description=(
                "Bir masaustu uygulamasini ya da adini verdigin pencereyi NAZIKCE "
                "kapatir (kaydetme sorusu cikabilir). Islem kullanicinin onayina "
                "tabidir; onay penceresi kapatilacak pencerenin gercek basligini "
                "gosterir. Kullanici acikca 'X'i kapat' dediginde kullan; 'name' "
                "olarak uygulama adini ya da pencere basligini ver (orn. 'Ayarlar')."
            ),
            parameters=_obj(
                {"name": types.Schema(type=_STR, description="Kapatilacak uygulamanin adi")},
                ["name"],
            ),
        ),
        types.FunctionDeclaration(
            name="close_active_tab",
            description=(
                "Odaktaki tarayici sekmesini kapatir (Ctrl+W). Kullanicinin "
                "onayina tabidir. Kullanici 'acilan sayfayi/sekmeyi kapat' "
                "dediginde kullan."
            ),
        ),
        types.FunctionDeclaration(
            name="reopen_last_closed",
            description=(
                "Bu oturumda en son kapattigin pencerenin uygulamasini yeniden acar. "
                "Kullanici 'yanlis seyi kapattin', 'geri ac' dediginde kullan. Uygulama "
                "acilir ama icindeki oturum/sekme geri gelmeyebilir; bunu kullaniciya soyle."
            ),
        ),
        types.FunctionDeclaration(
            name="check_email",
            description=(
                "Gelen kutusundaki son e-postalari listeler (gonderen, konu, tarih, uid). "
                "Kullanici 'mail geldi mi', 'gelen kutusuna bak' derse kullan."
            ),
            parameters=_obj(
                {
                    "unread_only": types.Schema(type=_BOOL, description="Sadece okunmamislar (varsayilan true)"),
                    "limit": types.Schema(type=_INT, description="Kac mesaj (varsayilan 10)"),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="read_email",
            description="Bir e-postanin tam icerigini getirir. `uid` check_email ciktisindaki degerdir.",
            parameters=_obj(
                {"uid": types.Schema(type=_STR, description="Mesajin uid'si")},
                ["uid"],
            ),
        ),
        types.FunctionDeclaration(
            name="search_email",
            description="Gelen kutusunda metin aramasi yapar (gonderen adi, konu, icerik).",
            parameters=_obj(
                {"query": types.Schema(type=_STR, description="Aranacak metin")},
                ["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="send_email",
            description=(
                "Bir e-posta gonderir. GONDERMEDEN once sistem onay penceresi acar; "
                "kullaniciya taslagi (kime/konu/govde) sozlu OKU ve onayini al, sonra "
                "cagir. Yanit ise `in_reply_to`'ya orijinal mesajin Message-ID'sini koy."
            ),
            parameters=_obj(
                {
                    "to": types.Schema(type=_STR, description="Alici e-posta adresi"),
                    "subject": types.Schema(type=_STR, description="Konu"),
                    "body": types.Schema(type=_STR, description="E-posta govdesi (duz metin)"),
                    "cc": types.Schema(type=_STR, description="CC adresi (istege bagli)"),
                },
                ["to", "body"],
            ),
        ),
        types.FunctionDeclaration(
            name="look_at_screen",
            description=(
                "Ekran gorusunu acar; birkac saniye icinde ekran goruntusu gelir. "
                "Kullanici 'ekranima bak', 'ne goruyorsun', 'su ekrandaki ...' "
                "dediginde kullan. Ekrani zaten goruyorsan tekrar cagirmana gerek yok."
            ),
        ),
        types.FunctionDeclaration(
            name="exit_application",
            description=(
                "JARVIS uygulamasinin kendisini tamamen kapatir. Kullanici "
                "'kendini kapat', 'JARVIS'i kapat', 'programdan cik' dediginde "
                "kullan. Kullanicinin onayina tabidir."
            ),
        ),
        types.FunctionDeclaration(
            name="open_website",
            description=(
                "Varsayilan tarayicida bir web sitesi acar. Tam URL, alan adi "
                "(orn. 'github.com'), kisayol ('youtube', 'gmail') veya arama "
                "sorgusu kabul eder."
            ),
            parameters=_obj(
                {"target": types.Schema(type=_STR, description="URL, alan adi, kisayol ya da arama metni")},
                ["target"],
            ),
        ),
        types.FunctionDeclaration(
            name="open_path",
            description=(
                "Bir dosyayi varsayilan uygulamasiyla ya da bir klasoru dosya "
                "gezgininde acar."
            ),
            parameters=_obj(
                {"path": types.Schema(type=_STR, description="Acilacak dosya veya klasor yolu")},
                ["path"],
            ),
        ),
    ]


def _panel_declarations() -> list[types.FunctionDeclaration]:
    """Icerik paneli: video, Wikipedia, belge, site, Spotify, haber, grafik, hava ve bilgi karti
    JARVIS arayuzunun ICINDE acilir."""
    n = types.FunctionDeclaration
    return [
        n(name="show_video",
          description=(
              "Bir YouTube videosunu JARVIS arayuzunun icindeki panelde oynatir. Kullanici '... videosunu ac', "
              "'... fragmanini goster', 'su YouTube linkini ac' dediginde kullan. Videoyu arac kendisi arar ve "
              "dogrular; video kimligi ya da link UYDURMA. Hata donerse video acilmamistir."
          ),
          parameters=_obj({"query": types.Schema(
              type=_STR, description="Aranacak video (orn. 'Interstellar fragman') ya da kullanicinin verdigi YouTube linki")},
              ["query"])),
        n(name="show_wikipedia",
          description=(
              "Bir kisi, yer, kurum ya da kavramin Wikipedia sayfasini JARVIS arayuzunun icindeki panelde acar "
              "ve gercek ozetini dondurur. '... kimdir', '... nedir', 'Wikipedia'da ac' gibi isteklerde kullan. "
              "Konu hakkinda YALNIZCA donen 'summary' metnindekileri soyle."
          ),
          parameters=_obj({"title": types.Schema(type=_STR, description="Sayfa basligi, orn. 'Albert Einstein', 'Izmir'")},
                          ["title"])),
        n(name="show_document",
          description=(
              "Bilgisayardaki bir belgeyi (PDF, .txt, .md) JARVIS arayuzunun icindeki panelde acar. 'CV'mi ac', "
              "'kira sozlesmesini goster', 'su PDF'i ac' gibi isteklerde kullan. Dosya adiyla arar; birden fazla "
              "belge uyarsa 'matches' listesi doner ve panel ACILMAZ: adlarini sayip sor, sonra secilenin "
              "'path' degeriyle yeniden cagir. Dosya yolu UYDURMA."
          ),
          parameters=_obj({"query": types.Schema(
              type=_STR, description="Dosya adindan kelimeler (orn. 'kira sozlesmesi') ya da 'matches' icindeki tam yol")},
              ["query"])),
        n(name="show_website",
          description=(
              "Bir web sitesini JARVIS arayuzunun icindeki panelde acar (ayri tarayici penceresi ACMAZ). "
              "Tam URL, alan adi ('github.com'), kisayol ('gmail') veya arama sorgusu kabul eder. Kullanici "
              "acikca 'tarayicida ac' demedikce site acmak icin open_website yerine bunu kullan. Bilgi, haber, "
              "fiyat ya da hava sormak icin arama sayfasi ACMA: show_news / show_market / show_weather / show_info."
          ),
          parameters=_obj({"target": types.Schema(type=_STR, description="URL, alan adi, kisayol ya da arama metni")},
                          ["target"])),
        n(name="show_spotify",
          description=(
              "Spotify 'su an caliyor' kartini JARVIS arayuzunun icinde gosterir (kapak, sarki, onceki/duraklat/"
              "sonraki). 'Spotify'i goster', 'ne caliyor goster' gibi isteklerde kullan. spotify_play zaten "
              "karti kendiliginden acar."
          )),
        n(name="show_news",
          description=(
              "Guncel haber basliklarini JARVIS arayuzunun icindeki panelde gosterir ve basliklari dondurur. "
              "'Haberleri goster', 'gundemde ne var', 'ekonomi / spor / teknoloji haberleri' gibi isteklerde "
              "kullan; arama sayfasi ACMA. Paneli acinca donen basliklardan 3-4 tanesini kisaca anlat; "
              "basliklarda olmayan ayrinti UYDURMA."
          ),
          parameters=_obj({"topic": types.Schema(
              type=_STR, description="Konu (orn. 'ekonomi', 'Fenerbahce', 'yapay zeka'); gundem icin bos birak")})),
        n(name="show_market",
          description=(
              "Borsa endeksi, hisse, doviz, altin ya da kripto fiyat GRAFIGINI JARVIS arayuzunun icindeki "
              "panelde gosterir ve rakamlari dondurur. 'Borsayi goster', 'dolar ne durumda', 'THY hissesi', "
              "'bitcoin grafigi' gibi isteklerde kullan. Sembolu arac kendisi bulur; sembol ya da fiyat "
              "UYDURMA. Paneli acinca fiyati, donem degisimini ve en yuksek/dusugu kisaca anlat."
          ),
          parameters=_obj({
              "query": types.Schema(type=_STR, description="Varlik adi: 'borsa', 'dolar', 'euro', 'altin', 'bitcoin', 'Turk Hava Yollari'..."),
              "period": types.Schema(type=_STR, description="Donem: 1g, 1h (hafta), 1ay (varsayilan), 3ay, 1y, 5y"),
          }, ["query"])),
        n(name="show_weather",
          description=(
              "Hava durumunu (simdi + 3 gunluk tahmin) JARVIS arayuzunun icindeki panelde gosterir ve veriyi "
              "dondurur. 'Hava nasil', 'yarin yagmur var mi', '... havasi' gibi isteklerde get_weather yerine "
              "bunu kullan ve kisaca anlat."
          ),
          parameters=_obj({"location": types.Schema(type=_STR, description="Sehir; bos birakilirsa kullanicinin sehri")})),
        n(name="show_map",
          description=(
              "Izmir'in 3B haritasini JARVIS arayuzunun icindeki panelde ve telefon uygulamasinda acar; bir yer verilirse kamera oraya "
              "('telefonumda haritayi ac' icin de bunu kullan, adb degil) "
              "suzulur. 'Izmir haritasini ac', 'Alsancak'i goster', 'Kordon'a git', 'haritada Bornova' gibi "
              "isteklerde kullan. Panel aciksa yeniden cagirmak yalnizca kamerayi tasir. Yeri arac kendisi "
              "bulur (yalnizca Izmir ili icinde); koordinat UYDURMA. Bulunamazsa soyle."
          ),
          parameters=_obj({"place": types.Schema(
              type=_STR, description="Izmir'de semt, mahalle, cadde ya da yer adi (orn. 'Alsancak', 'Saat Kulesi'); tum sehir icin bos")})),
        n(name="show_route",
          description=(
              "Izmir'de iki yer arasindaki rotayi JARVIS'in 3B haritasinda cizer, kamerayi rotaya yaklastirir "
              "('buradan', 'bulundugum yerden' denirse origin='konumum': telefonun GPS'i kullanilir) "
              "ve mesafe/sureyi dondurur. 'Buca'dan Alsancak'a rota', 'Konak'tan Kordon'a yurume yolu', "
              "'haritada ... yolunu goster' gibi isteklerde kullan. Toplu tasima (otobus, metro, ESHOT) "
              "sorulursa plan_route kullan. Baslangic soylenmediyse UYDURMA, kullaniciya sor. Yerleri ve "
              "yolu arac bulur; mesafe/sure uydurma, cizildi deme: yalnizca arac basariyla donerse soyle."
          ),
          parameters=_obj({
              "origin": types.Schema(type=_STR, description="Baslangic yeri (orn. 'Buca Egitim Fakultesi')"),
              "destination": types.Schema(type=_STR, description="Varis yeri (orn. 'Alsancak')"),
              "mode": types.Schema(type=_STR, description="araba (varsayilan), yuruyus ya da bisiklet"),
          }, ["origin", "destination"])),
        n(name="map_control",
          description=(
              "Acik 3B haritanin kamerasini yonetir: 'yakinlastir', 'biraz daha yaklas', 'uzaklastir', "
              "'haritayi dondur', 'Izmir geneline don'. Harita kapaliysa Izmir haritasini acar. Belirli bir "
              "yere gitmek icin show_map kullan."
          ),
          parameters=_obj({"action": types.Schema(
              type=_STR, description="zoom_in (yakinlastir), zoom_out (uzaklastir), rotate (dondur), reset (Izmir geneli)")},
              ["action"])),
        n(name="show_info",
          description=(
              "Kendi hazirladigin yazili icerigi JARVIS arayuzunun icindeki panelde gosterir: tarif, adim "
              "listesi, karsilastirma tablosu, ders/arastirma ozeti, plan. Kullanici bir seyi 'goster', "
              "'yaz', 'listele', 'tablo yap' dediginde ya da cevap ekranda gorulunce daha anlasilir "
              "olacaksa kullan; arama sayfasi ACMA. Govde sade Markdown: '## baslik', '- madde', "
              "'**kalin**', tablo. Emin olmadigin bilgiyi yazma; gerekirse once web_search ile dogrula. "
              "Paneli acinca icerigi kisaca sesli ozetle, tamamini okuma."
          ),
          parameters=_obj({
              "title": types.Schema(type=_STR, description="Kart basligi (kisa)"),
              "body": types.Schema(type=_STR, description="Markdown govde (en fazla ~6000 karakter)"),
          }, ["title", "body"])),
        n(name="close_panel",
          description=(
              "JARVIS arayuzundeki icerik panelini (video, haber, grafik, harita, bilgi karti, belge, site, Spotify) kapatir. "
              "'Kapat', 'videoyu kapat', 'paneli kapat' dediginde kullan."
          )),
    ]


def _mcp_browser_declarations() -> list[types.FunctionDeclaration]:
    """MCP gecidi (harici sunucu araclari) + tarayici ajani."""
    n = types.FunctionDeclaration
    return [
        n(name="mcp_servers",
          description="Bagli MCP sunucularini (GitHub, Notion, takvim, dosya sistemi vb. harici entegrasyonlar) "
                      "ve durumlarini listeler. Hazir araclarinla yapamadigin bir is icin once buna bak."),
        n(name="mcp_list_tools",
          description="Bir MCP sunucusundaki araclari ad, aciklama ve parametreleriyle listeler. "
                      "mcp_call'dan once aracin adini ve parametrelerini ogrenmek icin kullan.",
          parameters=_obj({"server": types.Schema(type=_STR, description="mcp_servers'taki sunucu adi"),
                           "query": types.Schema(type=_STR, description="Opsiyonel filtre (orn. 'issue', 'event')")},
                          ["server"])),
        n(name="mcp_call",
          description="Bir MCP sunucusundaki araci calistirir. Yazan/silen/gonderen araclar sistem onay penceresi acar.",
          parameters=_obj({"server": types.Schema(type=_STR),
                           "tool": types.Schema(type=_STR, description="mcp_list_tools'taki arac adi"),
                           "arguments_json": types.Schema(
                               type=_STR, description='Parametreler JSON nesnesi olarak, orn. {"query": "jarvis"}')},
                          ["server", "tool"])),
        n(name="browser_task",
          description="Bir web sitesinde cok adimli is yaptirir (siteye gir, ara, form doldur, bilgi bul, "
                      "kargo/okul sistemi kontrolu). Tarayici ajani (web_operatoru) kontrollu tarayicida yapar; "
                      "sonuc kopruden gelir. Odeme/satin alma/sifre girisi yapmaz.",
          parameters=_obj({"goal": types.Schema(type=_STR, description="Ne yapilacagi, net ve tam"),
                           "start_url": types.Schema(type=_STR, description="Opsiyonel baslangic adresi")},
                          ["goal"])),
        n(name="browser_open",
          description="JARVIS'in kontrollu tarayicisinda (kalici giris profili) bir adres acar. "
                      "Kullanicinin kendi tarayicisinda acmak icin open_website kullan.",
          parameters=_obj({"url": types.Schema(type=_STR)}, ["url"])),
    ]


def _okul_declarations() -> list[types.FunctionDeclaration]:
    """okul (BOTE Ders Merkezi) ders calisma uygulamasi kopru araclari."""
    n = types.FunctionDeclaration
    return [
        n(name="okul_status",
          description=(
              "okul (BOTE Ders Merkezi) ders uygulamasindan ozet: yaklasan sinavlar, "
              "geciken/yakin odevler ve bugunku ders programi. Kullanici 'okul durumu', "
              "'bugun ne var', 'programimda ne var', 'yaklasan sinav/odev' derse kullan."
          )),
        n(name="okul_next_exams",
          description="Onumuzdeki gunlerdeki sinavlari listeler.",
          parameters=_obj({"days": types.Schema(type=_INT, description="Kac gun ileriye bak (vars. 14)")})),
        n(name="okul_today_tasks",
          description="Bugun veya gecmiste teslim edilmesi gereken tamamlanmamis odevler. 'Bugun odevim var mi' turu."),
        n(name="okul_schedule",
          description="Bir gunun ders programi.",
          parameters=_obj({"day": types.Schema(
              type=_STR, description="'pazartesi'..'cuma', 'bugun', 'yarin' veya bos (bugun)")})),
        n(name="okul_gpa",
          description="Girilen harf notlarindan GANO (genel ortalama) ve yariyil ortalamalarini hesaplar."),
        n(name="okul_search_notes",
          description="okul'daki ders notlarinda metin arar.",
          parameters=_obj({"query": types.Schema(type=_STR)}, ["query"])),
        n(name="okul_add_task",
          description=(
              "okul'a yeni bir odev/gorev ekler. Degisiklik okul uygulamasi acikken "
              "birkac saniye icinde islenir. Kullanici 'su derse odev ekle', 'yarina "
              "odev yaz' derse kullan."
          ),
          parameters=_obj({
              "title": types.Schema(type=_STR, description="Odev basligi"),
              "course": types.Schema(type=_STR, description="Ders adi (istege bagli)"),
              "due": types.Schema(type=_STR, description="Teslim tarihi YYYY-MM-DD (istege bagli)"),
              "priority": types.Schema(type=_STR, description="Dusuk | Orta | Yuksek"),
              "notes": types.Schema(type=_STR, description="Not (istege bagli)"),
          }, ["title"])),
        n(name="okul_add_exam",
          description=(
              "okul'a yeni bir sinav ekler. Degisiklik okul uygulamasi acikken birkac "
              "saniye icinde islenir. Kullanici 'su tarihte sinav ekle' derse kullan."
          ),
          parameters=_obj({
              "course": types.Schema(type=_STR, description="Ders adi"),
              "exam_date": types.Schema(type=_STR, description="Sinav tarihi YYYY-MM-DD"),
              "exam_type": types.Schema(type=_STR, description="Vize | Final | Butunleme | Quiz (vars. Vize)"),
              "topics": types.Schema(type=_STR, description="Calisilacak konular, her satir bir madde (istege bagli)"),
              "exam_time": types.Schema(type=_STR, description="Saat, orn 10:00 (istege bagli)"),
              "location": types.Schema(type=_STR, description="Derslik / yer (istege bagli)"),
          }, ["course", "exam_date"])),
    ]


def _adb_declarations() -> list[types.FunctionDeclaration]:
    """Android ADB Control (Ultron modulu) - bagli telefon(lar)i yonetir."""
    n = types.FunctionDeclaration
    _dev = types.Schema(
        type=_STR,
        description=(
            "Hedef cihazin seri/ID'si (adb_list_devices ciktisindan). BOS BIRAK "
            "=> bagli TUM cihazlara uygulanir."
        ),
    )
    return [
        n(name="adb_list_devices",
          description=(
              "Bagli Android cihazlarin seri (ID) listesini getirir - hem USB hem "
              "WiFi (ip:port). 'telefonlar bagli mi', 'hangi cihazlar var' turu sorularda kullan."
          )),
        n(name="adb_connect_wifi",
          description=(
              "Ag uzerinden (WiFi) bir Android cihaza baglanir. `address` cihazin "
              "IP'si veya IP:PORT'u (orn. '192.168.1.42' ya da '192.168.1.42:5555'). "
              "Telefonda 'Kablosuz hata ayiklama' acik ve PC ile ayni WiFi aginda olmali. "
              "Android 11+ ilk kez baglaniyorsa once adb_pair_wifi gerekir. Kullanici "
              "'telefona kablosuz/wifi baglan', 'su IP'deki telefona baglan' derse kullan."
          ),
          parameters=_obj(
              {"address": types.Schema(type=_STR, description="Cihaz IP veya IP:PORT")},
              ["address"],
          )),
        n(name="adb_pair_wifi",
          description=(
              "Android 11+ kablosuz hata ayiklama eslesmesi + otomatik baglanti denemesi. "
              "Telefonda 'Gelistirici secenekleri > Kablosuz hata ayiklama > Cihazi eslestir' "
              "ekranindaki 'IP adresi ve port' (address) + '6 haneli kod' (code) verilir. "
              "Eslesmeden sonra arac cihazi otomatik baglamayi dener; sonuc "
              "connected=false donerse kullanicidan 'Kablosuz hata ayiklama' ANA "
              "ekranindaki (eslesme ekraninin degil) IP:PORT'u iste ve onu `connect_port` "
              "veya adb_connect_wifi ile kullan."
          ),
          parameters=_obj(
              {"address": types.Schema(type=_STR, description="Eslesme ekranindaki IP:PORT"),
               "code": types.Schema(type=_STR, description="6 haneli eslesme kodu"),
               "connect_port": types.Schema(type=_STR, description="Ana ekrandaki BAGLANTI portu (biliniyorsa)")},
              ["address", "code"],
          )),
        n(name="adb_enable_wifi",
          description=(
              "USB'den bagli bir cihazi kablosuz ADB moduna alir (tcpip + otomatik "
              "connect); sonrasinda USB kablosu cekilebilir. `device_id` bos ise "
              "USB'deki tum cihazlar. Kullanici 'kabloyu cekince de calissin', "
              "'telefonu kablosuz yap' derse kullan. Cihazin WiFi'si acik olmali."
          ),
          parameters=_obj({"device_id": types.Schema(
              type=_STR, description="USB cihaz seri (bos => USB'deki tum cihazlar)")})),
        n(name="adb_disconnect_wifi",
          description=(
              "Bir kablosuz (WiFi) ADB baglantisini keser. `address` verilmezse TUM "
              "ag baglantilari kesilir. USB baglantilari etkilenmez."
          ),
          parameters=_obj({"address": types.Schema(
              type=_STR, description="Kesilecek IP:PORT (bos => tum WiFi baglantilari)")})),
        n(name="adb_unlock_device",
          description=(
              "Bir Android cihazin (device_id) veya BOS ise bagli TUM cihazlarin "
              "ekranini acar: uyandirir, kilit ekranini kaydirir ve KAYITLI PIN varsa "
              "otomatik girer. Kullanici 'telefonu ac', 'telefonun kilidini ac' derse "
              "kullan - PIN parametresi verme, kayitli PIN kullanilir. `pin` yalnizca "
              "kullanici o an sozlu bir kod soylerse verilir. Kayitli PIN yoksa ve "
              "cihaz PIN korumaliysa ekran acilir ama kilit gecilemez."
          ),
          parameters=_obj({
              "device_id": _dev,
              "pin": types.Schema(type=_STR, description="Sadece kullanici o an soylediyse; normalde BOS birak"),
          })),
        n(name="adb_set_unlock_pin",
          description=(
              "Telefon ekran kilidi PIN'ini KALICI olarak kaydeder (jarvis-brain/.env, "
              "gizli dosya). Kullanici 'telefon sifresini kaydet 1234', 'PIN'im 1234' "
              "der veya 'telefonu ac dedigimde otomatik acilsin' isterse kullan. "
              "Kaydedildikten sonra adb_unlock_device PIN'i otomatik girer."
          ),
          parameters=_obj(
              {"pin": types.Schema(type=_STR, description="4-16 haneli PIN (sadece rakam)")},
              ["pin"],
          )),
        n(name="adb_open",
          description=(
              "ADB ile (USB/kablosuz hata ayiklama) Android cihazda bir uygulamayi veya URL/deep link'i acar. "
              "Telefon uygulamasi bagliyken telefonda uygulama acmak icin open_phone_app, harita icin show_map kullan. "
              "'https://...' veya 'scheme://...' => VIEW intent; 'com.paket/.Activity' "
              "=> belirli aktivite; duz paket adi ('com.spotify.music') => uygulamayi "
              "baslatir. device_id bos ise tum cihazlar."
          ),
          parameters=_obj(
              {"package_or_url": types.Schema(type=_STR, description="Paket adi, aktivite veya URL"),
               "device_id": _dev},
              ["package_or_url"],
          )),
        n(name="adb_play_media",
          description=(
              "Android cihaz(lar)da medya/muzik oynatmayi tetikler. URL verilirse "
              "(YouTube/Spotify/http) acilip oynatilir; duz metin verilirse "
              "('sarki adi') muzik uygulamasinda aranip calinmaya calisilir. "
              "Kullanici 'telefonlarda su sarkiyi cal' derse kullan. device_id bos => tum cihazlar."
          ),
          parameters=_obj(
              {"url_or_query": types.Schema(type=_STR, description="URL veya sarki/arama metni"),
               "device_id": _dev},
              ["url_or_query"],
          )),
        n(name="adb_shell",
          description=(
              "Android cihaz(lar)da serbest 'adb shell' komutu calistirir (esnek "
              "kullanim). Orn: 'settings get system screen_brightness', "
              "'input keyevent 26', 'pm list packages'. device_id bos => tum cihazlar."
          ),
          parameters=_obj(
              {"command": types.Schema(type=_STR, description="adb shell komut satiri"),
               "device_id": _dev},
              ["command"],
          )),
    ]


def _new_declarations() -> list[types.FunctionDeclaration]:
    n = types.FunctionDeclaration
    return [
        # --- proaktif ---
        n(name="set_reminder",
          description="Hatirlatici kurar. `when` dogal dil: '20 dakika sonra', 'yarin 09:00', '17:30', 'cuma 15:00'. Vadesinde JARVIS sesli soyler + telefon bildirimi.",
          parameters=_obj({"text": types.Schema(type=_STR, description="Hatirlatilacak sey"),
                           "when": types.Schema(type=_STR, description="Ne zaman (dogal dil)")},
                          ["text", "when"])),
        n(name="schedule_task",
          description=(
              "Bir ISI ileri bir saatte bir ajana yaptirir (tek seferlik). Ornek: 'saat 3'te su konuyu "
              "analiz et ve not al' -> schedule_task(task='su konuyu analiz et', when='15:00', save_note=true). "
              "Vakti gelince is ajana verilir, sonuc save_note=true ise notlara (Obsidian) kaydedilir ve sana "
              "kopruden gelir - kullaniciya sesli bildir. Sadece hatirlatma/cagirma icin set_reminder kullan. "
              "Bir cumlede birden fazla zamanli istek varsa HER BIRI icin ayri cagri yap."),
          parameters=_obj({"task": types.Schema(type=_STR, description="Yapilacak is, ajana verilecek tam talimat"),
                           "when": types.Schema(type=_STR, description="Ne zaman. 24 saatlik HH:MM tercih et ('saat 3' ogleden sonra ise '15:00'); 'yarin 09:00', '30 dakika sonra' da olur"),
                           "agent": types.Schema(type=_STR, description="Ajan kod adi (orn. arastirmaci); bos/auto = JARVIS secer"),
                           "save_note": types.Schema(type=_BOOL, description="Sonuc notlara kaydedilsin mi (varsayilan true)")},
                          ["task", "when"])),
        n(name="list_reminders", description="Bekleyen hatirlatici ve zamanli gorevleri listeler."),
        n(name="cancel_reminder", description="Bir hatirlaticiyi iptal eder (id veya metin parcasi).",
          parameters=_obj({"id_or_text": types.Schema(type=_STR)}, ["id_or_text"])),
        n(name="add_routine",
          description="Zamanlanmis rutin ekler. `schedule`: 'her gun 09:00', 'her saat', 'pazartesi 10:00'. Rutin tetiklendiginde `instruction` bir ajana verilir veya JARVIS'e komut olur.",
          parameters=_obj({"name": types.Schema(type=_STR), "schedule": types.Schema(type=_STR),
                           "instruction": types.Schema(type=_STR, description="Yapilacak is"),
                           "as_agent_task": types.Schema(type=_BOOL, description="Ajana gorev olarak ver (vars. true)")},
                          ["name", "schedule", "instruction"])),
        n(name="list_routines", description="Tanimli rutinleri listeler."),
        n(name="remove_routine", description="Bir rutini siler (id veya ad).",
          parameters=_obj({"id_or_name": types.Schema(type=_STR)}, ["id_or_name"])),
        # --- hizli araclar ---
        n(name="web_search", description="Google arama topraklamasiyla web'de arar, guncel bilgiyle ozet dondurur. 'X nedir', 'son durum', 'ara' turu sorular.",
          parameters=_obj({"query": types.Schema(type=_STR)}, ["query"])),
        n(name="get_weather", description="Bir sehrin guncel hava durumu + 3 gunluk tahmin.",
          parameters=_obj({"location": types.Schema(type=_STR, description="Sehir adi")}, ["location"])),
        n(name="calculate", description="Matematik ifadesi hesaplar. Orn: '(2+3)*4', 'sqrt(144)', 'sin(pi/2)'.",
          parameters=_obj({"expression": types.Schema(type=_STR)}, ["expression"])),
        n(name="convert_currency", description="Doviz cevirir. Orn: 100 USD -> TRY.",
          parameters=_obj({"amount": types.Schema(type=_NUM), "from_currency": types.Schema(type=_STR),
                           "to_currency": types.Schema(type=_STR)},
                          ["amount", "from_currency", "to_currency"])),
        n(name="translate", description="Metni hedef dile cevirir (en, tr, de, fr...).",
          parameters=_obj({"text": types.Schema(type=_STR), "target_lang": types.Schema(type=_STR)},
                          ["text", "target_lang"])),
        n(name="clipboard_get", description="Panodaki metni okur."),
        n(name="clipboard_set", description="Panoya metin koyar.",
          parameters=_obj({"text": types.Schema(type=_STR)}, ["text"])),
        # --- PC guc kullanicisi ---
        n(name="media_control", description="Medya/ses: play_pause | next | prev | stop | volume_up | volume_down | mute. "
                                            "Spotify icin spotify_* araclarini tercih et.",
          parameters=_obj({"action": types.Schema(type=_STR)}, ["action"])),
        # --- Spotify (Web API, Premium) ---
        n(name="spotify_play",
          description="Spotify'da muzik calar. Kullanici 'X cal/ac', 'sunu dinlemek istiyorum', 'muzigi devam ettir' "
                      "derse kullan. query bossa kaldigi yerden devam eder. Spotify kapaliysa PC'de acip calar.",
          parameters=_obj({"query": types.Schema(type=_STR, description="Sarki/sanatci/album/liste adi; bos = devam"),
                           "kind": types.Schema(type=_STR, description="track (vars.) | artist | album | playlist"),
                           "device": types.Schema(type=_STR, description="Bos = aktif cihaz; 'pc', 'telefon' veya cihaz adi")})),
        n(name="spotify_control",
          description="Spotify oynatma: pause | resume | next | previous | shuffle_on | shuffle_off | "
                      "repeat_off | repeat_track | repeat_context. 'Durdur', 'gec', 'onceki sarki', 'karistir'.",
          parameters=_obj({"action": types.Schema(type=_STR)}, ["action"])),
        n(name="spotify_now_playing", description="Spotify'da su an ne caldigini soyler ('bu sarki ne', 'ne caliyor')."),
        n(name="spotify_queue", description="Bir sarkiyi arayip Spotify kuyruguna ekler ('siradaki X olsun').",
          parameters=_obj({"query": types.Schema(type=_STR)}, ["query"])),
        n(name="spotify_volume", description="Spotify ses seviyesini 0-100 ayarlar ('sesi 30 yap').",
          parameters=_obj({"percent": types.Schema(type=_INT)}, ["percent"])),
        n(name="spotify_devices", description="Spotify cihazlarini (PC, telefon, hoparlor) ve aktif olani listeler."),
        n(name="window_action", description="Pencere: snap_left | snap_right | maximize | minimize | minimize_all | switch.",
          parameters=_obj({"action": types.Schema(type=_STR)}, ["action"])),
        n(name="list_processes", description="En cok bellek kullanan surecleri listeler.",
          parameters=_obj({"top_n": types.Schema(type=_INT, description="Kac tane (vars. 12)")})),
        n(name="kill_process", description="Bir uygulamayi/sureci NAZIKCE kapatir. Onaya tabi.",
          parameters=_obj({"name": types.Schema(type=_STR)}, ["name"])),
        n(name="move_path", description="Bir dosya/klasoru tasir. overwrite ile uzerine yazma onaya tabi.",
          parameters=_obj({"source": types.Schema(type=_STR), "destination": types.Schema(type=_STR),
                           "overwrite": types.Schema(type=_BOOL)}, ["source", "destination"])),
        n(name="copy_path", description="Bir dosya/klasoru kopyalar.",
          parameters=_obj({"source": types.Schema(type=_STR), "destination": types.Schema(type=_STR),
                           "overwrite": types.Schema(type=_BOOL)}, ["source", "destination"])),
        n(name="rename_path", description="Bir dosya/klasorun adini degistirir.",
          parameters=_obj({"path": types.Schema(type=_STR), "new_name": types.Schema(type=_STR)},
                          ["path", "new_name"])),
        n(name="make_folder", description="Klasor olusturur.",
          parameters=_obj({"path": types.Schema(type=_STR)}, ["path"])),
        n(name="zip_paths", description="Yollari (virgulle ayrilmis) zip'e sikistirir.",
          parameters=_obj({"sources": types.Schema(type=_STR), "archive_path": types.Schema(type=_STR)},
                          ["sources", "archive_path"])),
        n(name="find_files", description="Bir dizinde ada gore dosya arar (glob: '*.pdf', 'rapor*').",
          parameters=_obj({"pattern": types.Schema(type=_STR), "in_dir": types.Schema(type=_STR)},
                          ["pattern"])),
        # --- vision ---
        n(name="save_screenshot", description="Ekran goruntusu alir ve kaydeder.",
          parameters=_obj({"path": types.Schema(type=_STR, description="Hedef (bos ise data/screenshots)")})),
        n(name="ocr_screen", description="Ekrandaki tum metni cikarir (Gemini vision). 'Ekranda ne yaziyor' turu."),
        n(name="ocr_image", description="Bir gorsel dosyasindaki metni cikarir.",
          parameters=_obj({"path": types.Schema(type=_STR)}, ["path"])),
        n(name="record_screen", description="Ekrani belirtilen sure kaydeder (mp4).",
          parameters=_obj({"seconds": types.Schema(type=_NUM)}, ["seconds"])),
        # --- kod calistirma (onayli) ---
        n(name="run_python", description="Python kodu calistirir (sandbox, timeout). ONAYA TABI. Kapaliysa .env JARVIS_CODE_EXEC=true gerekir.",
          parameters=_obj({"code": types.Schema(type=_STR)}, ["code"])),
        n(name="run_shell", description="Kabuk komutu calistirir (PowerShell/Bash). ONAYA TABI.",
          parameters=_obj({"command": types.Schema(type=_STR)}, ["command"])),
        n(name="git_command", description="Git komutu. status/log/diff/branch onaysiz; add/commit/checkout ONAYA TABI.",
          parameters=_obj({"subcommand": types.Schema(type=_STR, description="orn 'status' veya 'commit -m mesaj'"),
                           "repo": types.Schema(type=_STR)}, ["subcommand"])),
        # --- GBrain ---
        n(name="kb_write", description="GBrain'e (kalici ortak hafiza) bir bilgi/not yazar.",
          parameters=_obj({"title": types.Schema(type=_STR), "content": types.Schema(type=_STR),
                           "tags": types.Schema(type=_STR, description="virgulle")},
                          ["title", "content"])),
        n(name="kb_search", description="GBrain'de anlamsal arama yapar.",
          parameters=_obj({"query": types.Schema(type=_STR), "k": types.Schema(type=_INT)}, ["query"])),
        n(name="kb_ask", description="GBrain kayitlarindan bir soruyu yanitlar.",
          parameters=_obj({"question": types.Schema(type=_STR)}, ["question"])),
        n(name="kb_recent", description="Son GBrain kayitlarini listeler.",
          parameters=_obj({"n": types.Schema(type=_INT)})),
        n(name="summarize_document", description="Bir belgeyi (txt/md/kod/pdf) ozetler; istege bagli GBrain'e kaydeder.",
          parameters=_obj({"path": types.Schema(type=_STR),
                           "save_to_gbrain": types.Schema(type=_BOOL)}, ["path"])),
        # --- disk bakimi ---
        n(name="cleanup_scan",
          description=(
              "Diskte guvenle temizlenebilecek yerleri olcer: gecici dosyalar, tarayici/pip "
              "onbellegi, Indirilenler/Masaustu'ndeki buyuk eski kurulum/arsiv dosyalari (id'li), "
              "cop kutusu. HICBIR SEY SILMEZ. 'Disk doldu', 'yer ac', 'temizlik' isteklerinde ONCE bu."
          ),
          parameters=_obj({"min_mb": types.Schema(type=_NUM, description="kurulum dosyasi alt siniri MB (vars. 50)"),
                           "older_days": types.Schema(type=_NUM, description="en az kac gunluk (vars. 14)")})),
        n(name="cleanup_run",
          description=(
              "Son cleanup_scan'e gore temizlik yapar. ONAYA TABI. Onbellek/gecici dosyalar silinir, "
              "kurulum dosyalari COP KUTUSUNA tasinir (geri alinabilir). Kullaniciya once taramayi "
              "ozetle, neyin silinecegini sor; sonra cagir."
          ),
          parameters=_obj({"categories": types.Schema(type=_STR, description="virgulle: temp, windows_temp, browser_cache, pip_cache, installers"),
                           "ids": types.Schema(type=_STR, description="virgulle tek tek kurulum dosyasi id'leri, orn 'i1,i3'")})),
        n(name="empty_recycle_bin",
          description="Geri Donusum Kutusu'nu bosaltir. GERI ALINAMAZ, ONAYA TABI. Yalnizca kullanici acikca isterse."),
        # --- kisisel hafiza (tum Obsidian kasalari) ---
        n(name="memory_search",
          description=(
              "Kullanicinin KENDI Obsidian kasalarinda anlamsal arama (Notlarim, universite, "
              "JARVIS Hafiza konusma kayitlari/notlari, JARVIS Bilgi Kasasi, Claude Memory). "
              "Kullanicinin gecmisi, projeleri, okulu, kararlari, 'ne konusmustuk / ne yapmistik' "
              "sorularinda ONCE bunu kullan. Ilk cagri ~10 sn surebilir."
          ),
          parameters=_obj({"query": types.Schema(type=_STR, description="dogal dilde sorgu"),
                           "vault": types.Schema(type=_STR, description="istege bagli kasa adi, orn 'JARVIS Hafiza'"),
                           "k": types.Schema(type=_INT, description="sonuc sayisi (vars. 6)")},
                          ["query"])),
        # --- jest kontrollu 3D HUD ---
        n(name="open_gesture_hud",
          description=(
              "El-jesti ile kontrol edilen 3D HUD'u kendi penceresinde acar (webcam onunde "
              "havada parmakla dondurme/zoom/exploded-view/parca secme). Kullanici 'jest "
              "kontrolunu ac', '3D modeli goster', 'HUD'u ac' gibi seylerde kullan."
          )),
    ]


def _comms_declarations() -> list[types.FunctionDeclaration]:
    """Haberlesme ajani: Gmail (OAuth) + Telegram."""
    n = types.FunctionDeclaration
    return [
        n(name="get_unread_emails",
          description="Gmail gelen kutusundaki OKUNMAMIS e-postalari listeler (gonderen, konu, tarih, ozet, uid). Gmail OAuth yapilandirilmamissa check_email kullan.",
          parameters=_obj({"limit": types.Schema(type=_INT, description="En fazla kac mail (varsayilan 10)")})),
        n(name="create_email_draft",
          description="Gmail'de bir e-posta TASLAGI olusturur, GONDERMEZ. reply_to_id (uid) verilirse o mailin zincirine eklenir. Kullanici 'taslak hazirla/taslaga kaydet' dediginde kullan.",
          parameters=_obj({"to": types.Schema(type=_STR, description="Alici e-posta adresi"),
                           "subject": types.Schema(type=_STR),
                           "body": types.Schema(type=_STR),
                           "reply_to_id": types.Schema(type=_STR, description="Yanitlanan mailin uid'si (opsiyonel)")},
                          ["to", "subject", "body"])),
        n(name="generate_auto_reply_draft",
          description="Bir e-postayi okuyup Sezai'nin uslubunda yanit yazar ve Gmail'e TASLAK kaydeder (GONDERMEZ). Donen reply_text'i kullaniciya oku; gondermek isterse send_email(in_reply_to=uid) ile gonder.",
          parameters=_obj({"message_id": types.Schema(type=_STR, description="Yanitlanacak mailin uid'si"),
                           "tone": types.Schema(type=_STR, description="samimi | resmi | kisa"),
                           "instructions": types.Schema(type=_STR, description="Yanitta olmasi gereken ek noktalar")},
                          ["message_id"])),
        n(name="send_telegram_message",
          description="Telegram'dan mesaj gonderir (sistem onay penceresi acar). chat_id bos ise varsayilan sohbete gider.",
          parameters=_obj({"text": types.Schema(type=_STR, description="Mesaj metni"),
                           "chat_id": types.Schema(type=_STR, description="Hedef sohbet id (opsiyonel)")},
                          ["text"])),
        n(name="get_latest_telegram_updates",
          description="Telegram'a gelen son mesajlari listeler (gonderen, metin, chat_id, message_id). 'Telegram'da ne var', 'mesaj geldi mi' gibi isteklerde kullan.",
          parameters=_obj({"limit": types.Schema(type=_INT, description="Kac mesaj (varsayilan 10)")})),
        n(name="reply_to_telegram_message",
          description="Belirli bir Telegram mesajina alintili yanit verir (sistem onay penceresi acar). chat_id ve message_id get_latest_telegram_updates ciktisindan alinir.",
          parameters=_obj({"chat_id": types.Schema(type=_STR),
                           "message_id": types.Schema(type=_INT),
                           "text": types.Schema(type=_STR)},
                          ["chat_id", "message_id", "text"])),
    ]


def _transit_declarations() -> list[types.FunctionDeclaration]:
    """Ulasim ajani: ESHOT durak/hat/saat, canli otobus, rota, Izmirim Kart."""
    n = types.FunctionDeclaration
    return [
        n(name="eshot_find_stop",
          description="Izmir ESHOT otobus duraklarini adiyla arar (orn. 'Konak', 'Bornova Metro'). Durak ID'si, konum ve duraktan gecen hatlari doner.",
          parameters=_obj({"query": types.Schema(type=_STR, description="Durak adi"),
                           "limit": types.Schema(type=_INT)},
                          ["query"])),
        n(name="eshot_nearby_stops",
          description="Verilen enlem/boylama en yakin ESHOT duraklarini mesafeyle listeler.",
          parameters=_obj({"lat": types.Schema(type=_NUM, description="Enlem"),
                           "lon": types.Schema(type=_NUM, description="Boylam"),
                           "radius_m": types.Schema(type=_INT, description="Yaricap metre (varsayilan 500)"),
                           "limit": types.Schema(type=_INT)},
                          ["lat", "lon"])),
        n(name="eshot_line_info",
          description="ESHOT hattinin adi, guzergahi ve hareket saatleri. next_from_start/next_from_end = SU ANDAN SONRAKI kalkislar; first_from_*/last_from_* = gunun ILK ve SON seferi ('ilk/son otobus kacta' sorularinda bunlari kullan). 'X otobusu ne zaman kalkiyor' sorularinda kullan.",
          parameters=_obj({"line_no": types.Schema(type=_STR, description="Hat numarasi (orn. '5', '302')"),
                           "day": types.Schema(type=_STR, description="Bos=bugun | hafta_ici | cumartesi | pazar"),
                           "next_count": types.Schema(type=_INT, description="Kac kalkis (varsayilan 5)")},
                          ["line_no"])),
        n(name="eshot_approaching_buses",
          description="Bir duraga yaklasan ESHOT otobuslerini CANLI getirir (line_no verilirse yalnizca o hat). stop_id once eshot_find_stop ile bulunur.",
          parameters=_obj({"stop_id": types.Schema(type=_STR),
                           "line_no": types.Schema(type=_STR, description="Opsiyonel hat numarasi")},
                          ["stop_id"])),
        n(name="plan_route",
          description="Izmir'de iki nokta arasi toplu tasima rotasi: Google Haritalar'i transit modunda acar ve varisa yakin ESHOT duraklarini onerir. origin bos ise mevcut konum.",
          parameters=_obj({"origin": types.Schema(type=_STR, description="Baslangic (bos=mevcut konum)"),
                           "destination": types.Schema(type=_STR, description="Varis noktasi")},
                          ["destination"])),
        n(name="izmirim_kart_balance",
          description="Izmirim Kart bakiye sorgusu: kayitli kart numarasini soyler ve resmi bakiye sayfasini acar (bakiye otomatik okunamaz)."),
    ]


def _phone_declarations() -> list[types.FunctionDeclaration]:
    """Telefon uygulamasi (C:\\dev\\jarvis-android): eylemler web/phone_link.py kanaliyla telefona gider."""
    n = types.FunctionDeclaration
    _who = types.Schema(type=_STR, description="Rehberdeki kisi adi ya da telefon numarasi (orn. 'Annem', '0532...')")
    return [
        n(name="phone_call",
          description=(
              "Kullanicinin TELEFONUNDAN arama baslatir ('annemi ara', 'Ahmet'i ara'). Telefon rehberden kisiyi bulur "
              "ve ekranda onay ister. Telefon uygulamasi bagli degilse hata doner; aradim deme, yalnizca arac "
              "basariyla donerse soyle."
          ),
          parameters=_obj({"contact": _who}, ["contact"])),
        n(name="send_sms",
          description="Telefondan SMS gonderir; telefonda onay karti cikar. Mesaj metnini kullanicinin soyledigi gibi yaz.",
          parameters=_obj({"contact": _who, "text": types.Schema(type=_STR, description="Mesaj metni")},
                          ["contact", "text"])),
        n(name="set_alarm",
          description="Telefonda alarm kurar ('yarin 7'de uyandir', 'alarm 06:45').",
          parameters=_obj({"time": types.Schema(type=_STR, description="SS:DD, 24 saat (orn. '07:30')"),
                           "label": types.Schema(type=_STR, description="Alarm etiketi (istege bagli)")}, ["time"])),
        n(name="set_timer",
          description="Telefonda geri sayim baslatir ('10 dakikalik zamanlayici kur').",
          parameters=_obj({"minutes": types.Schema(type=_NUM, description="Dakika (0.5 = 30 sn)"),
                           "label": types.Schema(type=_STR)}, ["minutes"])),
        n(name="open_phone_app",
          description="Telefonda bir uygulamayi acar ('telefonda WhatsApp'i ac', 'kamerayi ac'). PC'de acmak icin open_application.",
          parameters=_obj({"app": types.Schema(type=_STR, description="Uygulama adi")}, ["app"])),
        n(name="phone_location",
          description=(
              "Kullanicinin telefonunun GPS konumunu verir ('neredeyim'). Rota icin ayrica cagirma: show_route'a "
              "origin='konumum' ver."
          )),
        n(name="phone_status",
          description="Telefonun pil yuzdesi, sarj durumu ve ag bilgisi ('telefonumun sarji kac')."),
        n(name="ring_phone",
          description="'Telefonumu bul': telefon sessizde olsa da yuksek sesle calar."),
        n(name="send_file_to_phone",
          description=(
              "PC'deki bir dosyayi kullanicinin telefonuna gonderir ('bu PDF'i telefonuma at'). Tam dosya yolu gerekir; "
              "bilmiyorsan once find_files ile bul. Telefondan gelen dosyalar Downloads\\JARVIS klasorune duser."
          ),
          parameters=_obj({"path": types.Schema(type=_STR, description="PC'deki dosyanin tam yolu")}, ["path"])),
    ]


def _el_declarations() -> list[types.FunctionDeclaration]:
    """El Kontrolu (/el): kamera + el jestleri + efektler (tools/el_tools.py)."""
    n = types.FunctionDeclaration
    return [
        n(name="el_kontrolu_ac",
          description="El Kontrolu'nu acar: kamera ile el jestleri, efektler (ates, muhur, gezegen, simsek), "
                      "yuz HUD'u ve kitaplik. 'el kontrolunu ac', 'ellerimle yonetecegim' gibi isteklerde.",
          parameters=_obj({"demo": types.Schema(type=_BOOL, description="Kamerasiz demo (sentetik eller)")})),
        n(name="el_kontrolu_kapat", description="El Kontrolu'nu kapatir ('el kontrolunu kapat')."),
        n(name="el_gezegen",
          description="El Kontrolu'nde parmak uclarindaki parcacik gezegenini degistirir: 'Mars yap', "
                      "'Jupiter'e cevir'. Secenekler: Saturn, Dunya, Mars, Jupiter, Ay, Gunes.",
          parameters=_obj({"ad": types.Schema(type=_STR, description="Gezegen adi")}, ["ad"])),
    ]


def _kitaplik_declarations() -> list[types.FunctionDeclaration]:
    """Kullanicinin fiziksel kitapligi (core/bookshelf_store.py, tools/el_tools.py)."""
    n = types.FunctionDeclaration
    kitap = types.Schema(type=_STR, description="Kitap adi; bossa El Kontrolu'nde acik kitap")
    return [
        n(name="kitaplik_listele",
          description="Kullanicinin kendi kitapligini listeler. 'Kitapligimda ne var', 'raftan bir kitap oner', "
                      "'okudugum kitaplar' gibi sorularda MUTLAKA once bunu cagir; oneriyi YALNIZCA bu listeden yap.",
          parameters=_obj({"durum": types.Schema(type=_STR, description="okunacak | okunuyor | bitti"),
                           "sorgu": types.Schema(type=_STR, description="Ad/yazar aramasi")})),
        n(name="kitaplik_tara",
          description="Kameradaki kitapligi tarar ve kitap sirtlarini haritalar ('kitapligimi tara'). "
                      "El Kontrolu kapaliysa acar."),
        n(name="kitaplik_ekle",
          description="Kitapliga kitap ekler ('kitapligima Davranis'i ekle'). Kapak ve Jarvis'in sayfalari "
                      "arka planda dolar.",
          parameters=_obj({"ad": types.Schema(type=_STR), "yazar": types.Schema(type=_STR)}, ["ad"])),
        n(name="kitap_adlandir",
          description="El Kontrolu'nde acik olan, adi okunamamis kitaba ad verir: 'bu kitabin adi Davranis'. "
                      "Cagirmadan once kisaca 'Tamamdir efendim, ekliyorum' de.",
          parameters=_obj({"ad": types.Schema(type=_STR), "yazar": types.Schema(type=_STR)}, ["ad"])),
        n(name="kitap_not_ekle",
          description="Bir kitaba not ya da alinti ekler: 'Mulksuzler'e not ekle: ...', acik kitapta 'not al: ...', "
                      "'alinti ekle: ...'. Kitap kayitli degilse eklenir. Alinti metnini kullanici soyler; sen uretme.",
          parameters=_obj({"metin": types.Schema(type=_STR), "kitap": kitap,
                           "tur": types.Schema(type=_STR, description="not | alinti"),
                           "sayfa": types.Schema(type=_INT)}, ["metin"])),
        n(name="kitap_durum",
          description="Okuma durumunu/sayfasini kaydeder: 'Tahila Karsi'yi bitirdim', 'Oblomov'da 120. sayfadayim'.",
          parameters=_obj({"kitap": kitap,
                           "durum": types.Schema(type=_STR, description="okunacak | okunuyor | bitti"),
                           "sayfa": types.Schema(type=_INT)})),
        n(name="kitap_defter_doldur",
          description="Jarvis'in kitap defterini yazar (ozet, ana fikirler, yazar, temalar, neden okumali, "
                      "rafindan benzerler): 'Davranis'in sayfalarini doldur'.",
          parameters=_obj({"kitap": kitap, "yeniden": types.Schema(type=_BOOL, description="Var olani yeniden yaz")})),
        n(name="calibre_esitle",
          description="Kullanicinin Calibre e-kitap kutuphanesini kitapliga aktarir/gunceller "
                      "('Calibre'yi esitle', 'e-kitaplarimi ekle')."),
        n(name="kitap_tani",
          description="Kullanicinin kameraya gosterdigi / elinde tuttugu kitabi tanir ve kitapliga ekler "
                      "('elimdeki kitabi tani', 'bu kitabi ekle', 'bu hangi kitap'). Raf taramasi DEGIL."),
        n(name="kitap_ac",
          description="Kitabin e-kitap dosyasini Calibre kutuphanesinden acar ('Dune'u ac', 'bu kitabi oku'). "
                      "Kitap yalnizca fiziksel ise bunu soyle.",
          parameters=_obj({"kitap": kitap,
                           "format": types.Schema(type=_STR, description="EPUB | PDF | ... (istege bagli)")})),
        n(name="kitap_ozetle",
          description="Kitabin Jarvis ozetini getirir; sonra kendi sesinle kisaca oku. 'Bunu ozetle' (acik kitap).",
          parameters=_obj({"kitap": kitap})),
    ]


# Kapatilabilir arac gruplari (cekirdek her zaman acik). Gemini Live araclari oturum basinda sabitlenir;
# az kullanilan gruplari kapatmak modelin yanlis arac secmesini azaltir: .env -> JARVIS_TOOLS_OFF=adb,mcp_browser
TOOL_GROUPS = {
    "new": _new_declarations,
    "adb": _adb_declarations,
    "okul": _okul_declarations,
    "comms": _comms_declarations,
    "transit": _transit_declarations,
    "mcp_browser": _mcp_browser_declarations,
    "panel": _panel_declarations,
    "phone": _phone_declarations,
    "el": _el_declarations,
    "kitaplik": _kitaplik_declarations,
}


def disabled_tool_names(disabled: "set[str] | frozenset[str] | None") -> set[str]:
    """Kapali gruplardaki arac adlari (ToolRunner bunlari calistirmaz)."""
    return {d.name for g in (disabled or ()) if g in TOOL_GROUPS for d in TOOL_GROUPS[g]()}


def get_tools(disabled: "set[str] | frozenset[str] | None" = None) -> list[types.Tool]:
    return [types.Tool(function_declarations=build_declarations(disabled))]
