"""TELEFON departmani - Android telefon (ADB) kontrolu."""

from __future__ import annotations

from agents.departments._base import A, agent
from agents.schemas import Department, DepartmentSpec

DEPARTMENT = DepartmentSpec(
    key=Department.TELEFON,
    title="Telefon",
    description="Bagli Android telefonda (ADB) uygulama/URL acma, kilit acma ve medya oynatma.",
    agents=[
        agent("telefon_operatoru", "Telefon Operatörü",
              "Telefonda uygulama veya link acar, gerekirse ekran kilidini acar, bagli cihazlari listeler.",
              A.HUMAN_ASSISTED,
              "1) phone_devices ile bagli cihazi dogrula. 2) Gerekirse phone_unlock. "
              "3) phone_open ile paket adi veya URL ac. 4) Sonucu bildir.",
              "Sen TELEFON departmaninin Telefon Operatorusun. ADB araclariyla telefonda "
              "istenen uygulamayi veya linki acarsin. Cihaz yoksa kablosuz baglanti "
              "gerektigini kisaca soylersin. PIN'i asla yazma veya tekrar etme.",
              caps=["adb"], temperature=0.2),
        agent("medya_kumandasi", "Medya Kumandası",
              "Telefonda sarki/video arar ve oynatir (Spotify/YouTube).",
              A.FULLY_AUTONOMOUS,
              "1) phone_devices ile cihazi dogrula. 2) phone_play_media ile sorguyu veya URL'yi "
              "oynat. 3) Ne calindigini bildir.",
              "Sen TELEFON departmaninin Medya Kumandasisin. Istenen muzigi veya videoyu "
              "telefonda oynatirsin.",
              caps=["adb"], temperature=0.2),
    ],
)
