"""BILGI departmani - arastirma, bilgi bankasi (GBrain), notlar ve belge ozetleri."""

from __future__ import annotations

from agents.departments._base import A, agent
from agents.schemas import Department, DepartmentSpec

DEPARTMENT = DepartmentSpec(
    key=Department.BILGI,
    title="Bilgi",
    description="Web arastirmasi, kalici bilgi bankasi (GBrain), Obsidian notlari ve belge ozetleme.",
    agents=[
        agent("arastirmaci", "Araştırmacı",
              "Guncel web kaynaklariyla bir konuyu arastirir, kaynakli ve kisa bir ozet cikarir.",
              A.FULLY_AUTONOMOUS,
              "1) Soruyu netlestir. 2) Google aramasiyla guncel kaynaklari tara. "
              "3) 5-8 maddelik ozet + kaynak adlari.",
              "Sen BILGI departmaninin Arastirmacisisin. Guncel ve dogrulanabilir bilgiyi "
              "kisa, maddeli ve kaynakli Turkce ozetlersin. Bilmedigini uydurmazsin.",
              grounded=True, temperature=0.3),
        agent("bilgi_bankasi", "Bilgi Bankası",
              "Kalici bilgi bankasina (GBrain) not yazar veya anlamsal arama yapar.",
              A.FULLY_AUTONOMOUS,
              "1) Yazma mi arama mi belirle. 2) Yazarken baslik + etiket ver. "
              "3) Aramada en ilgili 3 kaydi ozetle.",
              "Sen BILGI departmaninin Bilgi Bankasi ajanisin. GBrain'e duzenli, etiketli "
              "notlar yazar ve gerektiginde bulup ozetlersin. Kullanicinin kendi notlarinda/"
              "gecmis konusmalarinda arama icin memory_search kullanirsin.",
              caps=["gbrain", "vault"], temperature=0.3),
        agent("not_katibi", "Not Kâtibi",
              "Soylenenleri gunluk nota (Obsidian) kaydeder, gecmis notlari hatirlatir.",
              A.FULLY_AUTONOMOUS,
              "1) Notu kisa ve anlasilir hale getir. 2) remember_note ile kaydet. "
              "3) Hatirlatma istenirse recall_notes ile bul.",
              "Sen BILGI departmaninin Not Katibisin. Notlari toparlar, kaydeder ve "
              "istendiginde geri getirirsin.",
              caps=["notes", "datetime"], temperature=0.3),
        agent("belge_ozetleyici", "Belge Özetleyici",
              "Bir metin/Markdown/kod dosyasini okuyup ozetler, ana fikirleri cikarir.",
              A.FULLY_AUTONOMOUS,
              "1) read_text_file ile belgeyi oku. 2) Tek paragraf ozet + 5 ana madde. "
              "3) Varsa yapilacaklar/tarihler listesi.",
              "Sen BILGI departmaninin Belge Ozetleyicisisin. Uzun belgeleri kisa ve "
              "yapilandirilmis Turkce ozetlere donusturursun.",
              caps=["files"], temperature=0.3),
    ],
)
