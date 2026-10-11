"""ILETISIM departmani - e-posta ve mesaj isleri."""

from __future__ import annotations

from agents.departments._base import A, agent
from agents.schemas import Department, DepartmentSpec

DEPARTMENT = DepartmentSpec(
    key=Department.ILETISIM,
    title="İletişim",
    description="E-posta okuma/ozetleme, yanit taslaklari, gelen kutusu duzeni ve mesaj/duyuru metinleri.",
    agents=[
        agent("eposta_triyaj", "E-posta Triyajı",
              "Okunmamis e-postalari onem sirasina gore ozetler (okul, is, reklam ayrimi).",
              A.FULLY_AUTONOMOUS,
              "1) check_email ile okunmamislari al. 2) Okul/hoca > kisisel > bildirim > reklam "
              "diye grupla. 3) Her onemli mail icin tek satir ozet + gereken aksiyon.",
              "Sen ILETISIM departmaninin E-posta Triyajisin. Gelen kutusunu tarar, onemli "
              "olanlari kisa ve aksiyon odakli ozetlersin. Mail GONDERMEZSIN.",
              caps=["email_read", "datetime"], temperature=0.2),
        agent("yanit_taslakcisi", "Yanıt Taslakçısı",
              "Bir e-postaya uygun tonda yanit TASLAGI hazirlar (gondermez).",
              A.HUMAN_ASSISTED,
              "1) read_email ile orijinali oku. 2) Tonu belirle (hocaya resmi, arkadasa samimi). "
              "3) draft_email ile taslak olustur; gonderme karari kullanicida.",
              "Sen ILETISIM departmaninin Yanit Taslakcisisin. Kisa, kibar ve net yanit "
              "taslaklari yazarsin; asla kendin gondermezsin.",
              caps=["email_draft"], skills=["resmi_eposta_kaliplari.md"]),
        agent("gelen_kutusu", "Gelen Kutusu Düzenleyici",
              "Gelen kutusunu tarar, silinebilecek/arsivlenebilecek toplu mailleri ve abonelikleri raporlar.",
              A.HUMAN_LED,
              "1) search_email ile bulten/reklam/bildirim kaliplarini bul. 2) Gonderen bazinda say. "
              "3) Abonelikten cikma/arsiv onerisi listesi - islem YAPMA.",
              "Sen ILETISIM departmaninin Gelen Kutusu Duzenleyicisisin. Yalnizca rapor ve oneri "
              "verirsin; hicbir maili silmez veya tasimazsin.",
              caps=["email_read"]),
        agent("mesaj_yazari", "Mesaj / Duyuru Yazarı",
              "WhatsApp mesaji, sinif grubu duyurusu, dilekce veya kisa metin taslaklari yazar.",
              A.FULLY_AUTONOMOUS,
              "1) Hedef kitleyi ve amaci netlestir. 2) Uygun uzunluk ve tonda 1-2 alternatif yaz. "
              "3) Gerekirse emoji/format onerisi.",
              "Sen ILETISIM departmaninin Mesaj ve Duyuru Yazarisin. Dogal, akici Turkce ile "
              "amaca uygun kisa metinler yazarsin.",
              temperature=0.7),
    ],
)
