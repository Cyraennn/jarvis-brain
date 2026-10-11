"""GUNLUK & MEDYA departmani - hatirlaticilar, gunluk brifing, hava, harcama, muzik."""

from __future__ import annotations

from agents.departments._base import A, agent
from agents.schemas import Department, DepartmentSpec

DEPARTMENT = DepartmentSpec(
    key=Department.GUNLUK,
    title="Günlük & Medya",
    description="Hatirlatici ve rutinler, sabah brifingi, hava durumu, kisisel harcama defteri ve PC'de muzik.",
    agents=[
        agent("hatirlatici", "Hatırlatıcı",
              "Dogal dille hatirlatici ve tekrarlayan rutin kurar, listeler, iptal eder.",
              A.FULLY_AUTONOMOUS,
              "1) Ne zaman + ne hatirlatilacak ayikla. 2) set_reminder / add_routine. "
              "3) Kurulan zamani acikca teyit et.",
              "Sen GUNLUK departmaninin Hatirlaticisisin. Hatirlatici ve rutinleri kurar, "
              "zamani net olarak teyit edersin.",
              caps=["schedule", "datetime"], temperature=0.2),
        agent("gunluk_brifing", "Günlük Brifing",
              "Sabah ozeti: hava durumu, bugunku dersler/sinavlar/odevler, onemli e-postalar.",
              A.FULLY_AUTONOMOUS,
              "1) get_weather (Izmir) + okul_status + check_email. 2) Her bolumden en onemli "
              "1-3 madde. 3) Gune dair tek cumlelik oneriyle bitir.",
              "Sen GUNLUK departmaninin Gunluk Brifing ajanisin. Sezai'ye kisa, enerjik ve "
              "maddeli bir gun ozeti sunarsin. Veri alinamayan bolumu atla.",
              caps=["quick", "okul", "email_read", "datetime", "vault"], temperature=0.4),
        agent("hava_durumu", "Hava Durumu",
              "Bir sehrin anlik ve gunluk hava durumunu, gerekirse giyim onerisiyle verir.",
              A.FULLY_AUTONOMOUS,
              "1) get_weather ile konumu sorgula (verilmezse Izmir). 2) Sicaklik, yagis, ruzgar. "
              "3) Kisa giyim/semsiye onerisi.",
              "Sen GUNLUK departmaninin Hava Durumu ajanisin. Kisa ve pratik hava raporu verirsin.",
              caps=["quick"], temperature=0.2),
        agent("harcama_defteri", "Harcama Defteri",
              "Kisisel harcamalari not eder, toplar ve donem ozeti cikarir.",
              A.HUMAN_ASSISTED,
              "1) Tutar/kategori/tarih ayikla. 2) remember_note ile 'Harcama:' onekiyle kaydet. "
              "3) Ozet istenirse recall_notes + calculate ile topla.",
              "Sen GUNLUK departmaninin Harcama Defterisin. Harcamalari duzenli kaydeder, "
              "kategori bazinda toplar ve kisa ozet verirsin.",
              caps=["notes", "quick", "datetime"], temperature=0.2),
        agent("muzik_dj", "Müzik DJ",
              "Bilgisayarda ruh haline/istege gore muzik veya YouTube/Spotify acar.",
              A.FULLY_AUTONOMOUS,
              "1) Istegi veya ruh halini yorumla (sarki, sanatci, liste). 2) spotify_play ile ara ve cal "
              "(kontrol icin spotify_control/spotify_queue/spotify_volume). 3) Spotify hata verirse "
              "open_app (spotify) ya da open_website_url ile ac. 4) Ne caldigini bildir.",
              "Sen GUNLUK departmaninin Muzik DJ'isin. Istege uygun muzigi Spotify'da calarsin.",
              caps=["pc_control", "spotify"], temperature=0.6),
    ],
)
