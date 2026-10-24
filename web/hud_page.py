"""El-jesti kontrollu 3D HUD sayfasi (`/hud`).

Ayri bir sayfa: mevcut mobil konsol (`page.py`) dokunulmadan, webcam onunde
havada el hareketiyle 3D modeli dondurme/zoom/exploded-view/parca secme.
MediaPipe (HandLandmarker) ve jest siniflandirmasi TAMAMEN tarayicida
calisir; Python'a yalnizca secilen parcanin adi (semantik intent) gider.
"""

from __future__ import annotations

_HTML = r"""<!doctype html><html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#05070d">
<title>CYRAEN · Gesture HUD</title>
<style>
:root{--bg:#05070d;--panel:#0b1120;--card:#0d1220;--border:#16233a;--cyan:#34e3f0;
--gold:#ffb84d;--mystic:#b47cff;--text:#cfe6ef;--dim:#7f97a6;--good:#3ff5b0;--bad:#ff5c72}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{width:100%;height:100%;overflow:hidden;background:var(--bg);color:var(--text);
font-family:"Rajdhani","Segoe UI",system-ui,sans-serif}
#scene{position:fixed;inset:0}
#cam{position:fixed;right:14px;bottom:14px;width:160px;height:120px;border-radius:10px;
border:1px solid var(--border);object-fit:cover;transform:scaleX(-1);opacity:.85;z-index:5}
#cam.hidden{display:none}
#overlay{position:fixed;inset:0;pointer-events:none;z-index:4}
.hud-top{position:fixed;top:0;left:0;right:0;padding:12px 16px;display:flex;gap:10px;align-items:center;
z-index:6;pointer-events:none;font-family:monospace;font-size:12px;letter-spacing:1px}
.hud-top .logo{font-weight:700;letter-spacing:4px;color:var(--cyan);pointer-events:none}
.pill{padding:3px 9px;border:1px solid var(--border);border-radius:10px;color:var(--dim);background:#05070daa}
.pill.locked{color:var(--gold);border-color:var(--gold)}
.pill.gesture{color:var(--good);border-color:var(--good)}
.hud-bottom{position:fixed;left:0;right:0;bottom:0;padding:14px 16px;display:flex;flex-direction:column;
gap:8px;z-index:6;align-items:center}
#caption{max-width:640px;background:#0b1120dd;border:1px solid var(--border);border-radius:12px;
padding:10px 14px;font-size:14px;line-height:1.4;text-align:center;min-height:1.4em}
#caption.empty{display:none}
.controls{display:flex;gap:8px;pointer-events:all}
.controls button{background:var(--card);border:1px solid var(--border);color:var(--text);
border-radius:9px;padding:8px 12px;font-size:12px;font-family:monospace;letter-spacing:1px}
.controls button.on{border-color:var(--cyan);color:var(--cyan)}
.controls select{background:var(--card);border:1px solid var(--border);color:var(--text);
border-radius:9px;padding:8px 10px;font-size:12px;font-family:monospace;max-width:220px}
#calibOverlay{position:fixed;inset:0;background:#05070de6;z-index:20;display:none;
flex-direction:column;align-items:center;justify-content:center;gap:18px;text-align:center;padding:24px}
#calibOverlay.show{display:flex}
#calibOverlay h2{font-family:monospace;letter-spacing:2px;color:var(--cyan);font-size:16px}
#calibOverlay p{color:var(--dim);font-size:13px;max-width:420px}
.ring{width:96px;height:96px;border-radius:50%;border:4px solid var(--border);
border-top-color:var(--cyan);animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.debug-hint{position:fixed;left:16px;bottom:70px;font-family:monospace;font-size:10px;
color:var(--dim);z-index:6;pointer-events:none;letter-spacing:1px}
</style></head><body>
<div class="hud-top">
  <span class="logo">C Y R A E N</span>
  <span class="pill" id="pConn">baglaniyor</span>
  <span class="pill" id="pGesture">jest: yok</span>
  <span class="pill locked" id="pLock" style="display:none">KILITLI</span>
</div>
<canvas id="scene"></canvas>
<video id="cam" autoplay playsinline muted></video>
<div class="debug-hint">Test tuslari: 1 dondur · 2 zoom · 3 exploded · 4 sec · 5 kilit · 6 parca ekle</div>
<div class="hud-bottom">
  <div id="caption" class="empty"></div>
  <div class="controls">
    <select id="camSelect" title="Webcam sec" style="display:none"></select>
    <button id="btnAddPart">+ Parca ekle</button>
    <button id="btnClearParts">Eklenenleri temizle</button>
    <button id="btnCalib">Kalibrasyon (10sn)</button>
    <button id="btnCam">Kamera</button>
    <button id="btnMic">🎙 Sesli komut</button>
  </div>
</div>
<div id="calibOverlay">
  <div class="ring"></div>
  <h2 id="calibStep">KALIBRASYON</h2>
  <p id="calibText">Birkac kez parmaklarinla sikistir (pinch), sonra avucunu ac ve kameraya dogru it.</p>
</div>
<script src="/gesture/smoothing.js"></script>
<script src="/gesture/gesture-engine.js"></script>
<script src="/gesture/deixis.js"></script>
<script src="/gesture/gesture-bridge.js"></script>
<script src="/gesture/calibration.js"></script>
<script type="module">
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { HandLandmarker, FilesetResolver } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";

const q = (s) => document.querySelector(s);
let KEY = new URLSearchParams(location.search).get("key") || "";
try { if (KEY) localStorage.setItem("jv_key", KEY); else KEY = localStorage.getItem("jv_key") || ""; } catch (e) {}
function api(path, body) {
  return fetch(path + (path.includes("?") ? "&" : "?") + "key=" + encodeURIComponent(KEY),
    body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {})
    .then((r) => r.json());
}

// ================= Three.js sahne =================
const canvas = q("#scene");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 100);
camera.position.set(0, 0, 8);

scene.add(new THREE.AmbientLight(0x334455, 1.2));
const key = new THREE.DirectionalLight(0x9fe8ff, 1.4);
key.position.set(3, 4, 5);
scene.add(key);

const modelGroup = new THREE.Group();
scene.add(modelGroup);

function part(name, geometry, color, position, explodeDir) {
  const mat = new THREE.MeshStandardMaterial({
    color, emissive: 0x34e3f0, emissiveIntensity: 0, metalness: 0.4, roughness: 0.35,
  });
  const mesh = new THREE.Mesh(geometry, mat);
  mesh.position.copy(position);
  mesh.name = name;
  modelGroup.add(mesh);
  return { name, mesh, explodeDirection: explodeDir.clone().normalize() };
}

const parts = [
  part("engine_block", new THREE.BoxGeometry(2.2, 1.6, 2.0), 0x2b3a55,
    new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, -1)),
  part("alternator", new THREE.CylinderGeometry(0.5, 0.5, 0.9, 24), 0x3d5170,
    new THREE.Vector3(1.6, 0.3, 0.6), new THREE.Vector3(1, 0.3, 1)),
  part("drive_belt", new THREE.TorusGeometry(0.55, 0.08, 12, 32), 0x1c2740,
    new THREE.Vector3(1.6, 1.0, 0.6), new THREE.Vector3(1, 1, 0.6)),
  part("battery", new THREE.BoxGeometry(0.8, 0.7, 0.7), 0x445b3a,
    new THREE.Vector3(-1.6, 0.4, 0.7), new THREE.Vector3(-1, 0.4, 1)),
  part("exhaust_manifold", new THREE.ConeGeometry(0.4, 1.4, 20), 0x5a4030,
    new THREE.Vector3(-0.2, -0.9, 1.3), new THREE.Vector3(0, -1, 1)),
];

const { createGestureBridge } = window.CyraenGestureBridge;
const { GestureEngine } = window.CyraenGestureEngine;
const { DeixisBuffer, containsDeixis, resolveCommand } = window.CyraenDeixis;
const { loadCalibration, runCalibration } = window.CyraenCalibration;

const deixis = new DeixisBuffer(800);
let locked = false;

const bridge = createGestureBridge({
  THREE, camera, modelGroup, parts,
  onLockChange: (isLocked) => { locked = isLocked; renderLockPill(); },
  onPartResolved: ({ gesture, part: partName, ts }) => {
    if (!partName) return;
    if (gesture === "hover") { deixis.push(partName, ts || Date.now()); setGesturePill(`hover: ${partName}`); }
    if (gesture === "select") { setGesturePill(`sec: ${partName}`); askAboutPart(partName); }
  },
});

// The engine only classifies landmarks; it knows nothing about Three.js and
// simply calls this callback with each semantic intent as it fires.
const engine = new GestureEngine(Object.assign({}, loadCalibration(), { onIntent: (intent) => bridge.onIntent(intent) }));

// ================= parca ekleme (kullanicinin kendi cisimleri) =================
const ADDED_GEOMETRIES = [
  () => new THREE.BoxGeometry(0.6, 0.6, 0.6),
  () => new THREE.SphereGeometry(0.4, 20, 16),
  () => new THREE.CylinderGeometry(0.35, 0.35, 0.7, 20),
  () => new THREE.ConeGeometry(0.35, 0.8, 20),
  () => new THREE.TorusGeometry(0.35, 0.12, 12, 28),
  () => new THREE.OctahedronGeometry(0.45),
];
const ADDED_COLORS = [0x5566aa, 0x8855aa, 0x55aa88, 0xaa8855, 0xaa5566, 0x557799];
let addedCount = 0;
const addedPartNames = [];

// New objects join the same select/explode/raycast pipeline as the built-in
// parts (bridge.addPart), so they can be taken apart and reassembled too.
function addRandomPart() {
  const geometry = ADDED_GEOMETRIES[Math.floor(Math.random() * ADDED_GEOMETRIES.length)]();
  const color = ADDED_COLORS[addedCount % ADDED_COLORS.length];
  const angle = Math.random() * Math.PI * 2;
  const radius = 2.2 + Math.random() * 1.2;
  const height = (Math.random() - 0.5) * 2.2;
  const position = new THREE.Vector3(Math.cos(angle) * radius, height, Math.sin(angle) * radius);
  const name = `custom_${++addedCount}`;
  const p = part(name, geometry, color, position, position.clone());
  bridge.addPart(p);
  addedPartNames.push(name);
  setCaption(`Eklendi: ${name} (avucunu ac + kameraya it -> parcala/birlestir)`);
  return p;
}

function clearAddedParts() {
  for (const name of addedPartNames.splice(0)) bridge.removePart(name);
  setCaption("Eklenen parcalar temizlendi.");
}

function renderLockPill() {
  q("#pLock").style.display = locked ? "" : "none";
}
function setGesturePill(text) {
  q("#pGesture").textContent = "jest: " + text;
}

function onResize() {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}
addEventListener("resize", onResize);
onResize();

let lastFrameTs = performance.now();
function renderLoop(now) {
  lastFrameTs = now;
  bridge.update();
  renderer.render(scene, camera);
  requestAnimationFrame(renderLoop);
}
requestAnimationFrame(renderLoop);

// ================= Debug panel (kamerasiz test) =================
addEventListener("keydown", (e) => {
  const ts = performance.now();
  if (e.key === "1") bridge.onIntent({ type: "rotate", dx: 0.02, dy: 0, ts });
  if (e.key === "2") bridge.onIntent({ type: "zoom", delta: 0.05, ts });
  if (e.key === "3") bridge.onIntent({ type: "explode", toggle: true, ts });
  if (e.key === "4") bridge.onIntent({ type: "select", x: 0.5, y: 0.5, ts });
  if (e.key === "5") bridge.onIntent({ type: "lock", locked: !locked, ts });
  if (e.key === "6") addRandomPart();
});

q("#btnAddPart").onclick = () => addRandomPart();
q("#btnClearParts").onclick = () => clearAddedParts();

// ================= agent cevabi (secim -> soru -> SSE -> konus) =================
let pendingGestureId = null;
function setCaption(text) {
  const c = q("#caption");
  c.textContent = text || "";
  c.classList.toggle("empty", !text);
}
function speak(text) {
  if (!text || !("speechSynthesis" in window)) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "tr-TR"; u.rate = 1.05;
    speechSynthesis.cancel(); speechSynthesis.speak(u);
  } catch (e) {}
}
async function askAboutPart(partName) {
  setCaption(`🔍 ${partName} seciliyor, CYRAEN'e soruluyor...`);
  try {
    const res = await api("/api/gesture", { gesture: "select", part: partName, ts: Date.now() });
    pendingGestureId = res && res.id ? res.id : null;
  } catch (e) { setCaption("Baglanti hatasi."); }
}
function connectSSE() {
  const ev = new EventSource("/api/events?key=" + encodeURIComponent(KEY));
  ev.onmessage = (e) => {
    try {
      const evt = JSON.parse(e.data);
      if (evt.kind === "connection") q("#pConn").textContent = evt.data;
      else if (evt.kind === "snapshot") q("#pConn").textContent = (evt.data.connection || "") + (evt.data.engine_state ? " · " + evt.data.engine_state : "");
      else if (evt.kind === "task" && pendingGestureId && evt.data.id === pendingGestureId) {
        if (evt.data.status === "done") { setCaption(evt.data.result || ""); speak(evt.data.result || ""); pendingGestureId = null; }
        else if (["failed", "blocked", "cancelled"].includes(evt.data.status)) { setCaption("Aciklama alinamadi."); pendingGestureId = null; }
      }
    } catch (x) {}
  };
  ev.onerror = () => { ev.close(); setTimeout(connectSSE, 3000); };
}
connectSSE();

// ================= webcam + MediaPipe HandLandmarker =================
const video = q("#cam");
let handLandmarker = null;
let numHands = 2;
let latestHands = [];

async function createLandmarker(delegate) {
  const vision = await FilesetResolver.forVisionTasks(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
  );
  return HandLandmarker.createFromOptions(vision, {
    baseOptions: {
      modelAssetPath: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
      delegate,
    },
    runningMode: "VIDEO",
    numHands,
  });
}

async function initVision() {
  try {
    handLandmarker = await createLandmarker("GPU");
  } catch (e) {
    console.warn("[gesture] GPU delegate basarisiz, CPU'ya dusuluyor", e);
    numHands = 1;
    try { handLandmarker = await createLandmarker("CPU"); }
    catch (e2) { console.warn("[gesture] HandLandmarker hic baslatilamadi", e2); }
  }
}

function cameraErrorMessage(e) {
  const name = e && e.name;
  if (name === "NotAllowedError" || name === "PermissionDeniedError")
    return "Kamera izni verilmedi - adres cubugundaki kamera simgesinden izin ver.";
  if (name === "NotFoundError" || name === "OverconstrainedError")
    return "Webcam bulunamadi - bilgisayarina bagli bir webcam oldugundan emin ol.";
  if (name === "NotReadableError" || name === "TrackStartError")
    return "Webcam baska bir uygulama tarafindan kullaniliyor - CYRAEN ana penceresindeki kamera butonu acik olabilir, onu kapatip tekrar dene.";
  return "Webcam acilamadi (" + (name || "bilinmeyen hata") + ").";
}

async function populateCameraList(selectedId) {
  const sel = q("#camSelect");
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const cams = devices.filter((d) => d.kind === "videoinput");
    sel.innerHTML = "";
    cams.forEach((d, i) => {
      const opt = document.createElement("option");
      opt.value = d.deviceId;
      opt.textContent = d.label || `Kamera ${i + 1}`;
      if (d.deviceId === selectedId) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.style.display = cams.length > 1 ? "" : "none";
    return cams;
  } catch (e) {
    return [];
  }
}

async function startStream(deviceId) {
  if (video.srcObject) video.srcObject.getTracks().forEach((t) => t.stop());
  const videoConstraints = deviceId
    ? { deviceId: { exact: deviceId }, width: 640, height: 480 }
    : { width: 640, height: 480, facingMode: "user" }; // "user" = bilgisayarin on/webcam kamerasi
  const stream = await navigator.mediaDevices.getUserMedia({ video: videoConstraints, audio: false });
  video.srcObject = stream;
  await video.play();
  return stream;
}

async function initCamera() {
  try {
    const stream = await startStream();
    const track = stream.getVideoTracks()[0];
    await populateCameraList(track && track.getSettings().deviceId);
    setCaption("");
  } catch (e) {
    console.warn("[gesture] webcam acilamadi", e);
    setCaption(cameraErrorMessage(e));
  }
}

q("#camSelect").onchange = async (e) => {
  try { await startStream(e.target.value); }
  catch (err) { setCaption(cameraErrorMessage(err)); }
};

const GESTURE_TARGET_MS = 1000 / 30;
let lastDetectTs = 0;
function gestureLoop(now) {
  requestAnimationFrame(gestureLoop);
  if (!handLandmarker || video.readyState < 2) return;
  if (now - lastDetectTs < GESTURE_TARGET_MS) return;
  lastDetectTs = now;
  let result;
  try { result = handLandmarker.detectForVideo(video, now); } catch (e) { return; }
  latestHands = (result && result.landmarks) || [];
  // The <video> preview is CSS-mirrored (scaleX(-1)) so it feels like looking
  // in a mirror, but MediaPipe detects on the raw, unmirrored frame. Without
  // this flip, moving a hand right looks right in the preview but drives
  // rotate/select the opposite way, which is what made objects feel
  // unresponsive/backwards to control.
  for (const hand of latestHands) {
    for (const pt of hand) pt.x = 1 - pt.x;
  }
  engine.processFrame(latestHands, now); // intents are delivered via the onIntent callback above
  if (!latestHands.length) setGesturePill("yok");
}
requestAnimationFrame(gestureLoop);

initVision();
initCamera();

// ================= kalibrasyon =================
q("#btnCalib").onclick = async () => {
  q("#calibOverlay").classList.add("show");
  const steps = ["Sikistir (pinch) ve birak, birkac kez tekrarla...", "Simdi avucunu ac ve kameraya dogru it..."];
  q("#calibText").textContent = steps[0];
  setTimeout(() => { q("#calibText").textContent = steps[1]; }, 5000);
  const { config } = await runCalibration({ getLandmarks: () => latestHands, durationMs: 10000 });
  engine.configure(config);
  q("#calibOverlay").classList.remove("show");
  setCaption("Kalibrasyon tamamlandi.");
};

// ================= kamera goster/gizle =================
q("#btnCam").onclick = () => { video.classList.toggle("hidden"); };

// ================= sesli komut + deixis =================
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR) {
  const rec = new SR();
  rec.lang = "tr-TR"; rec.interimResults = false; rec.continuous = false;
  rec.onresult = (e) => {
    let text = e.results[e.results.length - 1][0].transcript;
    if (containsDeixis(text)) {
      const resolved = deixis.resolve(Date.now());
      if (resolved) {
        text = resolveCommand(text, resolved);
        setCaption(`🎙 "${text}" -> CYRAEN'e gonderildi`);
      }
    }
    api("/api/say", { text }).catch(() => setCaption("Gonderilemedi."));
  };
  q("#btnMic").onclick = () => { try { rec.start(); q("#btnMic").classList.add("on"); } catch (e) {} };
  rec.onend = () => q("#btnMic").classList.remove("on");
} else {
  q("#btnMic").onclick = () => setCaption("Bu tarayici sesli girisi desteklemiyor.");
}
</script>
</body></html>"""


def render_hud_page() -> str:
    return _HTML
