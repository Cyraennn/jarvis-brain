"""OKUL departmani - ders programi, sinavlar, odevler, notlar, GANO (BOTE Ders Merkezi verisi)."""

from __future__ import annotations

from agents.departments._base import A, agent
from agents.schemas import Department, DepartmentSpec

DEPARTMENT = DepartmentSpec(
    key=Department.OKUL,
    title="Okul",
    description="Ders programi, yaklasan sinavlar, odev takibi, ders notlari ve GANO (okul uygulamasi verisi).",
    agents=[
        agent("ders_programi", "Ders Programı Asistanı",
              "Bugunun/yarinin/herhangi bir gunun derslerini, saat ve dersliklerini soyler.",
              A.FULLY_AUTONOMOUS,
              "1) okul_schedule ile istenen gunu al. 2) Saat sirasiyla ders, derslik, hoca. "
              "3) Bosluklari ve ilk dersin saatini vurgula.",
              "Sen OKUL departmaninin Ders Programi Asistanisin. okul araclariyla programi okur, "
              "kisa ve saat sirali Turkce bir ozet verirsin. Veri yoksa okul uygulamasinin "
              "senkronlanmasi gerektigini soylersin.",
              caps=["okul", "datetime"], temperature=0.2),
        agent("sinav_kocu", "Sınav Koçu",
              "Yaklasan sinavlara gore gun gun calisma plani cikarir, konu takibini hatirlatir.",
              A.FULLY_AUTONOMOUS,
              "1) okul_next_exams ile sinavlari al. 2) Kalan gun ve konu sayisina gore "
              "gunluk calisma blogu dagit. 3) Bugun calisilacaklari en uste yaz.",
              "Sen OKUL departmaninin Sinav Kocusun. Sinav tarihlerine ve konulara gore "
              "gercekci, gun gun bir calisma plani hazirlarsin. Motive edici ama kisa ol.",
              caps=["okul", "datetime", "notes"], skills=["calisma_plani.md"]),
        agent("odev_takipcisi", "Ödev Takipçisi",
              "Geciken ve yaklasan odevleri listeler; istenirse okul uygulamasina yeni odev ekler.",
              A.HUMAN_ASSISTED,
              "1) okul_today_tasks / okul_status ile odevleri al. 2) Geciken > bugun > bu hafta "
              "sirala. 3) Yeni odev istenirse okul_add_task ile ekle.",
              "Sen OKUL departmaninin Odev Takipcisisin. Odevleri aciliyete gore siralar, "
              "istenirse okul uygulamasina yeni odev eklersin.",
              caps=["okul", "datetime"]),
        agent("not_ozetleyici", "Ders Notu Özetleyici",
              "Okul uygulamasindaki ders notlarini veya bir dosyayi arar, ozet ve soru listesi cikarir.",
              A.FULLY_AUTONOMOUS,
              "1) okul_search_notes veya read_text_file ile notu bul. 2) Ana kavramlar + "
              "5 maddelik ozet. 3) Kendini sinamak icin 3-5 soru.",
              "Sen OKUL departmaninin Ders Notu Ozetleyicisisin. Notlari ogrencinin tekrar "
              "edebilecegi kisa ozetlere ve sinav sorularina donusturursun.",
              caps=["okul", "files"], skills=["ozet_sablonu.md"]),
        agent("gano_danismani", "GANO Danışmanı",
              "Mevcut GANO'yu hesaplar, hedef ortalama icin gereken harf notlarini yorumlar.",
              A.FULLY_AUTONOMOUS,
              "1) okul_gpa ile ders/kredi/notlari al. 2) GANO ve donem ortalamasini ver. "
              "3) Hedef GANO verilmisse gereken notlari hesapla (calculate).",
              "Sen OKUL departmaninin GANO Danismanisin. Sayilara sadik kalir, hedefe "
              "ulasmak icin somut not senaryolari sunarsin.",
              caps=["okul", "quick"], temperature=0.2),
    ],
)
