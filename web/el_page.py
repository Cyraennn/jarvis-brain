"""El Kontrolu ✋ + Kitaplik 📚 sayfasi (/el).

Tum mantik `web/static/gesture/*.js` dosyalarinda; burasi iskelet HTML + stil + yapilandirma.
Yapilandirma (`window.EL_CONFIG`): kullanici adi (yuz HUD etiketi) ve yerel MediaPipe
dosyalarinin varligi (`scripts/el_modeli_indir.py` ile indirilmisse CDN'e gidilmez).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

_MODELS = Path(__file__).parent / "static" / "models"

_SCRIPTS = [
    "smoothing.js", "hand-features.js", "poses.js", "controller.js", "shelf-geom.js", "shelf-drift.js",
    "demo-hands.js", "fx-particles.js", "fx-fire.js", "fx-seal.js", "fx-planet.js", "fx-burst.js",
    "fx-audio.js", "fx-settings.js", "frame-scheduler.js", "face-hud.js", "bookshelf.js", "shelf-calib.js",
    "el-app.js",
]

_CSS = """
:root{--bg:#000;--fg:#ffffffde;--dim:#ffffff80;--or:#ff8c42;--or2:#ffcf8a;--cy:#34e3f0;--glass:rgba(10,10,12,.62)}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);overflow:hidden;
  font:15px Rajdhani,'Segoe UI',system-ui,sans-serif;user-select:none}
#cam,#demoSrc{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;transform:scaleX(-1) var(--shake,);
  filter:saturate(.9) brightness(.82)}
#demoSrc{display:none}
body.demo #demoSrc{display:block} body.demo #cam{display:none}
#fx{position:fixed;inset:0;width:100%;height:100%;pointer-events:none}
.bar{position:fixed;left:0;right:0;display:flex;align-items:center;gap:8px;padding:12px 16px;z-index:5;
  pointer-events:none}
.top{top:0;background:linear-gradient(#000c,#0000)}
.logo{font-weight:700;letter-spacing:.22em;color:var(--or);display:flex;align-items:center;gap:10px;margin-right:auto}
.orb{width:14px;height:14px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#ffe2bf,var(--or) 45%,#7a2e0c);
  box-shadow:0 0 14px var(--or)}
.pill{pointer-events:auto;border:1px solid #ff8c4255;background:var(--glass);border-radius:999px;padding:4px 11px;
  font-size:13px;color:var(--dim);white-space:nowrap;display:inline-flex;align-items:center;gap:6px}
.pill.bad{color:#ff6b6b;border-color:#ff6b6b88}
button.pill{cursor:pointer;color:var(--or2)} button.pill:hover{border-color:var(--or)}
button.pill.busy{animation:pulse 1s infinite;border-color:var(--or)}
#pThink{display:none;color:var(--or2)} #pThink::before{content:"";width:7px;height:7px;border-radius:50%;
  background:var(--or);animation:pulse 1s infinite}
@keyframes pulse{50%{opacity:.25}}
#caption{position:fixed;left:50%;bottom:44px;transform:translateX(-50%) translateY(10px);max-width:min(900px,90vw);
  text-align:center;font-size:21px;line-height:1.35;padding:10px 20px;border-radius:14px;background:#000a;
  border:1px solid #ff8c4240;opacity:0;transition:.25s;z-index:5;pointer-events:none}
#caption.show{opacity:1;transform:translateX(-50%)}
#caption[data-who=user]{color:var(--or2)} #caption[data-who=demo]{color:var(--cy);font-size:18px}
#toast{position:fixed;top:64px;left:50%;transform:translateX(-50%);padding:8px 16px;border-radius:10px;
  background:#000c;border:1px solid var(--or);color:var(--or2);opacity:0;transition:.2s;z-index:7;pointer-events:none}
#toast.show{opacity:1}
#warn{position:fixed;top:64px;left:0;right:0;text-align:center;padding:8px;background:#ff8c42dd;color:#000;
  font-weight:700;letter-spacing:.14em;display:none;z-index:6}
#warn.show{display:block}
.panel{position:fixed;right:16px;top:60px;width:330px;max-height:calc(100vh - 140px);overflow:auto;background:var(--glass);
  backdrop-filter:blur(12px);border:1px solid #ff8c4255;border-radius:14px;padding:12px 16px;z-index:8;display:none}
.panel.show{display:block}
.panel h3{margin:2px 0 10px;color:var(--or);letter-spacing:.2em;font-size:14px}
.fxrow{display:flex;align-items:center;gap:8px;padding:5px 0;cursor:pointer}
.fxrow input{accent-color:var(--or)} .fxrow select{margin-left:auto;background:#111;color:var(--fg);border:1px solid #333;border-radius:6px}
.fxhint{color:var(--dim);font-size:12px;line-height:1.45}
#calibPanel{left:16px;right:auto}
.calrow{display:flex;flex-wrap:wrap;gap:6px}
.calrow button{background:#111;color:var(--fg);border:1px solid #444;border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit}
.calrow button.primary{border-color:var(--or);color:var(--or2)}
.calstatus{margin:10px 0 4px;color:var(--or2);font-size:13px;min-height:18px}
.calinput{position:fixed;z-index:9;width:280px;padding:7px 10px;background:#0b0b0d;color:#fff;border:1px solid var(--or);
  border-radius:8px;font:15px 'Segoe UI',sans-serif}
#off{position:fixed;inset:0;display:none;place-items:center;background:#000;z-index:10;text-align:center}
body.off #off{display:grid} body.off #cam{visibility:hidden}
#off .big{font-size:64px;margin-bottom:8px} #off p{color:var(--dim)}
#off button{margin-top:14px;font:inherit;font-size:17px;padding:10px 22px;border-radius:999px;background:#111;
  color:var(--or2);border:1px solid var(--or);cursor:pointer}
body.clean .bar,body.clean .panel,body.clean #toast{display:none!important}
@media (max-width:640px){.pill.opt{display:none}.panel{width:calc(100vw - 32px)}}
"""

_BODY = """
<video id="cam" playsinline muted></video>
<canvas id="demoSrc"></canvas>
<canvas id="fx"></canvas>
<div class="bar top">
  <div class="logo"><span class="orb"></span>JARVIS · EL KONTROLÜ</div>
  <span class="pill" id="pThink">DÜŞÜNÜYOR</span>
  <span class="pill" id="pConn">● bağlı</span>
  <span class="pill" id="pFps">– FPS</span>
  <span class="pill" id="pHands">✋ 0</span>
  <span class="pill opt" id="pDet">– ms</span>
  <span class="pill opt" id="pMode">…</span>
  <span class="pill opt" id="pCam">📷</span>
  <button class="pill" id="btnHeld" title="Kameraya tuttuğun kitabı tanı (B)">📖 elimdeki kitap</button>
  <button class="pill" id="btnShelf" title="Kitaplık ayarı (K)">📚 kitaplık</button>
  <button class="pill" id="btnFx" title="Efektler (E)">⚙ efektler</button>
</div>
<div id="warn">KAMERA KIPIRDAMIŞ · KİTAPLIĞI YENİDEN TARA (K)</div>
<div id="toast"></div>
<div id="caption"></div>
<div class="panel" id="fxPanel"></div>
<div class="panel" id="calibPanel"></div>
<div id="off"><div><div class="big">✋</div><h2>El Kontrolü kapalı</h2>
  <p>H tuşu ya da “Jarvis, el kontrolünü aç”. Kamera kapalı.</p><button id="btnOn">Aç</button></div></div>
"""


def _local_models() -> dict[str, bool]:
    def ok(name: str) -> bool:
        return (_MODELS / name).is_file()

    return {
        "bundle": ok("vision_bundle.mjs") and ok("vision_wasm_internal.wasm") and ok("vision_wasm_internal.js"),
        "hand": ok("hand_landmarker.task"),
        "face": ok("blaze_face_short_range.tflite"),
    }


def render_el_page(demo: bool = False) -> str:
    from config.settings import get_settings

    cfg = {"user": get_settings().user_name, "models": _local_models()}
    # </script> kacisi: JSON icinde '<' kalmasin
    cfg_js = json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c")
    scripts = "\n".join(f'<script src="/gesture/{html.escape(s)}"></script>' for s in _SCRIPTS)
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS · El Kontrolü</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&display=swap" rel="stylesheet">
<style>{_CSS}</style></head>
<body>
{_BODY}
<script>window.EL_CONFIG = {cfg_js};
if (new URLSearchParams(location.search).get("el") === "demo") document.body.classList.add("demo");</script>
{scripts}
</body></html>"""
