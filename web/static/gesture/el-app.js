// El Kontrolu ✋ ana uygulamasi (/el). Kamera -> MediaPipe (el 30 Hz, yuz 5 Hz) -> duruslar ->
// efektler / Cyraen kontrolleri / kitaplik. Kamera goruntusu hicbir yere gonderilmez; yalnizca
// kitaplik taramasinda (K modu, ya da "kitapligimi tara") tek kare yerel CYRAEN sunucusuna gider.
(function () {
  "use strict";
  const JEL = window.JEL;
  const HF = window.CyraenHandFeatures, P = window.CyraenPoses, C = window.CyraenController;
  const G = window.CyraenShelfGeom, D = window.CyraenDemoHands, S = window.CyraenSmoothing;
  const CFG = window.EL_CONFIG || {};
  const MP_VER = "0.10.14";
  const CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VER}`;
  const HAND_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
  const FACE_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite";

  const q = (s) => document.querySelector(s);
  const params = new URLSearchParams(location.search);
  let KEY = params.get("key") || "";
  try { if (KEY) localStorage.setItem("jv_key", KEY); else KEY = localStorage.getItem("jv_key") || ""; } catch (e) { /* yoksay */ }
  const DEMO = params.get("el") === "demo";
  const SHELF_DEMO = DEMO && params.get("kitaplik") === "1";

  // ------------------------------------------------------------ sunucu
  function withKey(path) { return path + (path.includes("?") ? "&" : "?") + "key=" + encodeURIComponent(KEY); }
  async function api(path, body) {
    const r = await fetch(withKey(path), body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    const j = await r.json().catch(() => ({}));
    if (!r.ok && j && !j.error) j.error = "HTTP " + r.status;
    return j;
  }
  async function apiRaw(path, blob) {
    const r = await fetch(withKey(path), { method: "POST", headers: { "Content-Type": blob.type || "image/jpeg" }, body: blob });
    return r.json().catch(() => ({ error: "HTTP " + r.status }));
  }

  // ------------------------------------------------------------ durum
  const st = {
    active: true, ui: true, skeleton: DEMO, // demoda kamera yok: sentetik eller iskeletle gorunur speaking: false, thinking: false, thinkingT: 0,
    lastWelcome: -1e9, pendingPlanet: null, fps: 0, handsN: 0, detMs: 0, drawMs: 0,
  };
  const settings = new JEL.FxSettings();
  const audio = new JEL.FxAudio();
  const particles = new JEL.Particles(800);
  const fire = new JEL.Fire(particles);
  const seal = new JEL.Seal();
  const planets = new JEL.PlanetSystem(particles);
  const burst = new JEL.Burst(particles);
  const lightning = new JEL.Lightning(particles);
  const trail = new JEL.Trail();
  const holds = new C.HoldController(C.KONTROLLER);
  const face = new JEL.FaceHud(CFG.user || "Sezai");
  const drift = new window.CyraenShelfDrift.DriftWatch();
  planets.onEvent = (type) => {
    if (!settings.get("sesler")) return;
    if (type === "form" || type === "morph") audio.chime();
    if (type === "explode") audio.boom();
    if (type === "throw") audio.whoosh();
  };
  audio.setMuted(!settings.get("sesler"));
  settings.onChange = (k, v) => {
    if (k === "sesler") audio.setMuted(!v);
    if (k === "yuz" && !v) face.reset();
    if (k === "kitaplik") bookshelf.enabled = v;
  };

  const canvas = q("#fx");
  const ctx = canvas.getContext("2d");
  const video = q("#cam");
  const demoCanvas = q("#demoSrc");
  let source = DEMO ? demoCanvas : video;
  let demoTruth = null;

  function T() {
    const vw = source.videoWidth || source.width || 1280, vh = source.videoHeight || source.height || 720;
    return G.coverTransform(vw, vh, canvas.width, canvas.height);
  }

  const app = {
    api, apiRaw, audio, demo: DEMO, key: KEY, T, canvas, drift,
    source: () => (DEMO ? demoCanvas : (video.readyState >= 2 ? video : null)),
    toast, say, reload, demoTruth: () => demoTruth,
  };
  const bookshelf = new JEL.Bookshelf(app);
  bookshelf.enabled = settings.get("kitaplik");
  app.bookshelf = bookshelf;
  const calib = new JEL.ShelfCalib(app, q("#calibPanel"));

  // ------------------------------------------------------------ arayuz yardimcilari
  let toastTimer = 0;
  function toast(msg) {
    const el = q("#toast");
    el.textContent = msg; el.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
  }
  let capTimer = 0;
  function caption(text, who) {
    const el = q("#caption");
    el.textContent = text; el.dataset.who = who || "cyraen"; el.classList.add("show");
    clearTimeout(capTimer); capTimer = setTimeout(() => el.classList.remove("show"), Math.min(14000, 3500 + text.length * 55));
  }
  function setThinking(on) { st.thinking = on; st.thinkingT = performance.now(); q("#pThink").style.display = on ? "inline-flex" : "none"; }

  async function say(text) {
    if (DEMO) { toast("Demo: komut gönderilmez"); return; }
    caption("→ " + text, "user");
    setThinking(true);
    const r = await api("/api/say", { text, source: "EL" }).catch((e) => ({ error: String(e) }));
    if (r.error) { setThinking(false); toast("Gönderilemedi: " + r.error); }
  }
  async function control(action) {
    if (DEMO) { toast("Demo: komut gönderilmez"); return; }
    const r = await api("/api/control", { action }).catch((e) => ({ error: String(e) }));
    if (r.error) toast("Kontrol: " + r.error);
  }

  // ------------------------------------------------------------ elimdeki kitap
  let heldBusy = false;
  async function readHeldBook() {
    if (DEMO) { toast("Demo: kamera yok"); return; }
    if (heldBusy) return;
    const src = app.source();
    if (!src) { toast("Kamera hazır değil"); return; }
    heldBusy = true;
    q("#btnHeld").classList.add("busy");
    toast("📖 Kitap okunuyor… kapağı kameraya düz tutun");
    if (settings.get("sesler")) audio.scan();
    try {
      const blob = await calib._grabFrame();
      // kart icin karenin ortasi (kitap genelde ortada tutulur)
      const vw = src.videoWidth, vh = src.videoHeight;
      const img = document.createElement("canvas");
      img.width = Math.round(vw * 0.4); img.height = Math.round(vh * 0.8);
      img.getContext("2d").drawImage(src, vw * 0.3, vh * 0.1, vw * 0.4, vh * 0.8, 0, 0, img.width, img.height);
      const r = await apiRaw("/api/kitaplik/eldeki", blob);
      if (r.error) throw new Error(r.error);
      if (!r.kitap) { toast(r.mesaj || "Kitap okunamadı"); return; }
      await reload();
      const book = bookshelf.books.find((b) => b.id === r.kitap.id) || r.kitap;
      toast((r.durum === "eklendi" ? "Kitaplığa eklendi: " : "Zaten kitaplıkta: ") + book.ad
        + (book.yazar ? " · " + book.yazar : ""));
      if (settings.get("sesler")) audio.confirm();
      bookshelf.putBack();
      bookshelf.showBook(book, img);
    } catch (e) {
      toast("Kitap okunamadı: " + e.message);
    } finally {
      heldBusy = false;
      q("#btnHeld").classList.remove("busy");
    }
  }

  async function reload() {
    if (DEMO) return;
    const snap = await api("/api/kitaplik").catch(() => null);
    if (snap && snap.books) {
      bookshelf.setData(snap);
      drift.setReference(snap.referans);
    }
  }

  // ------------------------------------------------------------ kamera
  let cams = [], camIdx = -1, stream = null;
  const CAM_KEY = "jv_el_cam_v1";
  // Telefon / sanal kameralar (Windows Telefon Baglantisi, DroidCam, OBS...) geri planda kalir;
  // varsayilan bilgisayarin kendi kamerasidir. C ile secilen kamera bu cihazda hatirlanir.
  const REMOTE_CAM = /s2\d|galaxy|iphone|pixel|phone|telefon|ki[sş]iye ait|link|ba[gğ]lant|droidcam|iriun|epoccam|virtual|sanal|obs|camo|continuity/i;
  async function listCams() {
    cams = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
    return cams;
  }
  function preferredCam() {
    let saved = "";
    try { saved = localStorage.getItem(CAM_KEY) || ""; } catch (e) { /* yoksay */ }
    const si = cams.findIndex((c) => c.deviceId && c.deviceId === saved);
    if (si >= 0) return si;
    const local = cams.findIndex((c) => c.label && !REMOTE_CAM.test(c.label));
    return local >= 0 ? local : 0;
  }
  async function startCamera() {
    if (DEMO) return;
    stopCamera();
    try {
      if (camIdx < 0) {
        await listCams();
        // etiketler izin verilmeden bos gelir: once kisa bir izin akisi ac
        if (cams.length && !cams.some((c) => c.label)) {
          const tmp = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
          tmp.getTracks().forEach((t) => t.stop());
          await listCams();
        }
        camIdx = preferredCam();
      }
      const devId = cams[camIdx] && cams[camIdx].deviceId;
      stream = await navigator.mediaDevices.getUserMedia({
        video: Object.assign({ width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
          devId ? { deviceId: { exact: devId } } : { facingMode: "user" }),
        audio: false,
      });
      video.srcObject = stream;
      await video.play();
      if (!cams.length) cams = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
      const label = (stream.getVideoTracks()[0] || {}).label || "kamera";
      q("#pCam").textContent = "📷 " + label.slice(0, 28);
    } catch (e) {
      toast(cameraError(e));
      q("#pCam").textContent = "📷 yok";
    }
  }
  function stopCamera() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  async function nextCamera() {
    await listCams();
    if (cams.length < 2) { toast("Başka kamera yok (telefonu DroidCam/Iriun ile bağlayabilirsiniz)"); return; }
    camIdx = (camIdx + 1) % cams.length;
    try { localStorage.setItem(CAM_KEY, cams[camIdx].deviceId || ""); } catch (e) { /* yoksay */ }
    await startCamera();
    toast("Kamera: " + (cams[camIdx].label || camIdx + 1));
  }
  function cameraError(e) {
    const n = e && e.name;
    if (n === "NotAllowedError") return "Kamera izni verilmedi — adres çubuğundaki kamera simgesinden izin verin.";
    if (n === "NotFoundError" || n === "OverconstrainedError") return "Kamera bulunamadı.";
    if (n === "NotReadableError") return "Kamera başka bir uygulamada açık (CYRAEN ana penceresindeki kamera?).";
    return "Kamera açılamadı (" + (n || e) + ")";
  }

  // ------------------------------------------------------------ MediaPipe
  let handLm = null, faceDet = null;
  async function loadVision() {
    if (DEMO) { q("#pMode").textContent = "DEMO"; return; }
    const local = CFG.models || {};
    let mod, wasm;
    try {
      if (local.bundle) { mod = await import("/models/vision_bundle.mjs"); wasm = "/models"; }
    } catch (e) { console.warn("[el] yerel MediaPipe yuklenemedi, CDN'e dusuluyor", e); }
    if (!mod) { mod = await import(CDN); wasm = CDN + "/wasm"; }
    const fileset = await mod.FilesetResolver.forVisionTasks(wasm);
    const handPath = local.hand ? "/models/hand_landmarker.task" : HAND_URL;
    const facePath = local.face ? "/models/blaze_face_short_range.tflite" : FACE_URL;
    for (const delegate of ["GPU", "CPU"]) {
      try {
        handLm = await mod.HandLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: handPath, delegate }, runningMode: "VIDEO", numHands: 2,
          minHandDetectionConfidence: 0.55, minTrackingConfidence: 0.5,
        });
        q("#pMode").textContent = delegate;
        break;
      } catch (e) { console.warn(`[el] HandLandmarker ${delegate} basarisiz`, e); }
    }
    if (!handLm) toast("El takip modeli açılamadı (internet? `python scripts/el_modeli_indir.py`)");
    try {
      faceDet = await mod.FaceDetector.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: facePath, delegate: "GPU" }, runningMode: "VIDEO", minDetectionConfidence: 0.6,
      });
    } catch (e) {
      try { faceDet = await mod.FaceDetector.createFromOptions(fileset, { baseOptions: { modelAssetPath: facePath, delegate: "CPU" }, runningMode: "VIDEO" }); }
      catch (e2) { console.warn("[el] FaceDetector acilamadi", e2); }
    }
  }

  // ------------------------------------------------------------ eller
  const handState = new Map(); // id -> {tracker, filters, last, center}
  let nextHandId = 1;
  let hands = [];             // islenmis eller (ekran px)

  function assignIds(rawHands, t) {
    const out = [], used = new Set();
    for (const lm of rawHands) {
      const c = HF.palmCenter(lm);
      let best = null, bestD = Infinity;
      for (const [id, s] of handState) {
        if (used.has(id) || t - s.last > 400) continue;
        const d = Math.hypot(s.center.x - c.x, s.center.y - c.y);
        if (d < bestD) { best = id; bestD = d; }
      }
      const size = HF.handSize(lm);
      let id = best !== null && bestD < Math.max(120, size * 2.5) ? best : null;
      if (id === null) {
        id = nextHandId++;
        handState.set(id, { tracker: new P.PoseTracker(), filters: lm.map(() => new S.FilteredPoint({ minCutoff: 1.6, beta: 0.02 })), last: t, center: c });
      }
      used.add(id);
      out.push({ id, lm });
    }
    for (const [id, s] of handState) if (t - s.last > 1500) handState.delete(id);
    return out;
  }

  function processHands(rawHands, t, smooth) {
    const out = [];
    for (const { id, lm } of assignIds(rawHands, t)) {
      const s = handState.get(id);
      const sm = smooth ? lm.map((p, i) => s.filters[i].update(p, t)) : lm;
      const f = HF.features(sm);
      const r = s.tracker.update(f, t);
      s.last = t; s.center = f.palm;
      out.push({ id, lm: sm, f, pose: r.pose, prev: r.prev, changed: r.changed, events: r.events, velocity: r.velocity });
    }
    hands = out;
    st.handsN = out.length;
    react(out, t);
  }

  function detectHands(src, t) {
    if (!handLm || !st.active) return;
    const t0 = performance.now();
    const res = handLm.detectForVideo(src, t);
    st.detMs = st.detMs * 0.8 + (performance.now() - t0) * 0.2;
    const tr = T();
    const raw = (res.landmarks || []).map((lms) => lms.map((p) => {
      const sp = G.rawToScreen(tr, p.x, p.y);
      return { x: sp.x, y: sp.y, z: p.z * tr.vw * tr.s };
    }));
    processHands(raw, t, true);
  }

  function detectFaces(src, t) {
    if (!faceDet || !st.active || !settings.get("yuz")) return;
    const res = faceDet.detectForVideo(src, t);
    const tr = T(), vw = tr.vw, vh = tr.vh;
    const dets = (res.detections || []).map((d) => {
      const b = d.boundingBox;
      return { rect: G.boxToScreen(tr, { x: b.originX / vw, y: b.originY / vh, w: b.width / vw, h: b.height / vh }),
        score: (d.categories && d.categories[0] && d.categories[0].score) || 0 };
    });
    face.feed(dets, t);
  }

  // ------------------------------------------------------------ jestlere tepki
  const heldPlanet = new Map(); // hand id -> planet
  function react(hs, t) {
    const busy = bookshelf.busy() || calib.active;
    const shelfOn = settings.get("kitaplik") && bookshelf.hasShelf();
    const inShelf = (p) => shelfOn && bookshelf.inZone(p);
    // cimdik birakma -> gezegen suzer/firlar
    for (const h of hs) {
      const pl = heldPlanet.get(h.id);
      if (pl && h.pose !== "pinch") {
        planets.release(pl, h.velocity.px, h.velocity.py);
        heldPlanet.delete(h.id);
      }
    }
    for (const [id, pl] of heldPlanet) if (!hs.some((h) => h.id === id)) { planets.release(pl, 0, 0); heldPlanet.delete(id); }
    if (busy) return;

    for (const h of hs) {
      // yumruk -> acik el: patlat
      for (const e of h.events) {
        if (e.type !== "burst" || !settings.get("patlatma") || inShelf(h.f.palm)) continue;
        const near = planets.planets.find((pl) => pl.state !== "explode" && Math.hypot(pl.x - h.f.palm.x, pl.y - h.f.palm.y) < pl.R * 3 + h.f.size);
        if (near) { planets.explode(near); burst.kick(1.2); }
        else { burst.wave(h.f.palm.x, h.f.palm.y, h.f.size); if (settings.get("sesler")) audio.boom(); }
      }
      // cimdik -> gezegen
      // diger el bir gezegen tutarken ona yakin cimdik = iki elle buyutme (yeni gezegen degil)
      const grabsHeld = [...heldPlanet.values()].some((pl) =>
        Math.hypot(pl.x - h.f.pinchPt.x, pl.y - h.f.pinchPt.y) < pl.R * 5 + h.f.size * 1.5);
      if (h.pose === "pinch" && settings.get("gezegen") && !inShelf(h.f.pinchPt) && !heldPlanet.has(h.id)
          && h.changed && !grabsHeld) {
        const kind = st.pendingPlanet || planets.nextKind(settings.v.gezegenSabit);
        st.pendingPlanet = null;
        heldPlanet.set(h.id, planets.spawn(kind, h.f.pinchPt.x, h.f.pinchPt.y - h.f.size * 0.3, h.f.size * 0.42));
      }
    }
  }

  // her cizim karesinde (surekli efektler)
  function continuous(hs, t, dt) {
    const busy = bookshelf.busy() || calib.active;
    const shelfOn = settings.get("kitaplik") && bookshelf.hasShelf();
    const inShelf = (p) => shelfOn && bookshelf.inZone(p);
    const noFxInShelf = (p) => settings.get("rafAtesYok") && inShelf(p);
    if (busy) return;
    const open = hs.filter((h) => h.pose === "open");
    for (const h of open) {
      if (settings.get("ates") && !noFxInShelf(h.f.palm)) fire.feed(h, dt);
    }
    if (open.length >= 2 && settings.get("muhur")) for (const h of open) seal.feed(h.id, h, t);
    // gezegeni tut / iki elle buyut
    const pinchers = hs.filter((h) => h.pose === "pinch");
    for (const h of pinchers) {
      const pl = heldPlanet.get(h.id);
      if (!pl) continue;
      const other = pinchers.find((o) => o !== h);
      if (other && !heldPlanet.has(other.id)) {
        const mx = (h.f.pinchPt.x + other.f.pinchPt.x) / 2, my = (h.f.pinchPt.y + other.f.pinchPt.y) / 2;
        const d = Math.hypot(h.f.pinchPt.x - other.f.pinchPt.x, h.f.pinchPt.y - other.f.pinchPt.y);
        planets.hold(pl, mx, my, (h.f.roll + other.f.roll) / 2, Math.max(20, d * 0.42));
      } else {
        planets.hold(pl, h.f.pinchPt.x, h.f.pinchPt.y - h.f.size * 0.3, h.f.roll);
      }
    }
    // isaret parmaklari
    const pointers = hs.filter((h) => h.pose === "point" && !noFxInShelf(h.f.indexTip));
    if (pointers.length >= 2 && settings.get("simsek")) {
      lightning.feed(pointers[0].f.indexTip, pointers[1].f.indexTip, dt);
      if (settings.get("sesler") && Math.random() < dt * 9) audio.zap();
    } else if (pointers.length === 1 && settings.get("iz") && !inShelf(pointers[0].f.indexTip)) {
      trail.feed(pointers[0].f.indexTip, t);
    }
    if (settings.get("sesler")) audio.fire(fire.intensity);
  }

  // ------------------------------------------------------------ basili tutma kontrolleri
  let rings = [];
  function controls(hs, t) {
    rings = [];
    if (!settings.get("kontroller") || bookshelf.busy() || calib.active) { holds.reset(); return; }
    const pts = hs.filter((h) => !(bookshelf.hasShelf() && bookshelf.inZone(h.f.palm)))
      .map((h) => ({ id: h.id, pose: h.pose, x: h.f.palm.x, y: h.f.palm.y }));
    const r = holds.update(pts, { speaking: st.speaking }, t);
    rings = r.rings;
    for (const f of r.fired) {
      if (settings.get("sesler")) audio.confirm();
      const e = f.rule.eylem;
      if (e.tip === "komut") say(e.metin);
      else if (e.tip === "kontrol") { control(e.action); toast(f.rule.ad || e.action); }
    }
  }

  // ------------------------------------------------------------ demo
  let demoPlayer = null, demoShelf = null;
  function setupDemo() {
    if (!DEMO) return;
    const W = 1280, H = 720;
    demoCanvas.width = W; demoCanvas.height = H;
    const g = demoCanvas.getContext("2d");
    if (SHELF_DEMO) {
      demoTruth = D.drawShelf(g, W, H);
      demoShelf = g.getImageData(0, 0, W, H);
      bookshelf.setData({ books: demoTruth.boxes.map((b) => Object.assign({ durum: "okunuyor", notlar: [{ metin: "Demo notu: bu sayfa sentetik." }], alintilar: [],
        defter: { bilinmiyor: false, ozet: `${b.ad} için demo özeti. Gerçek kullanımda Cyraen bu sayfayı kitabı tanıyorsa yazar.`,
          ana_fikirler: ["Demo ana fikir 1", "Demo ana fikir 2", "Demo ana fikir 3", "Demo ana fikir 4"],
          yazar_hakkinda: `${b.yazar} (demo).`, temalar: ["demo"], neden_oku: "Demo.", kime_uygun: "Herkese.", benzerler: [] } }, b)),
      raf: demoTruth.raf });
      drift.setReference({ gri: window.CyraenShelfDrift.thumb(demoCanvas) });
      const target = (i) => {
        const b = demoTruth.boxes[i];
        if (!b) return null;
        const r = G.boxToScreen(T(), b.kutu);
        return { x: r.x + r.w / 2, y: r.y + r.h / 2 };
      };
      demoPlayer = new D.ScriptPlayer(D.shelfScript(target));
    } else {
      g.fillStyle = "#050505"; g.fillRect(0, 0, W, H);
      demoPlayer = new D.ScriptPlayer(D.effectScript());
    }
  }
  let demoStep = -1, demoLastDet = 0, demoShift = 0;
  window.JEL_DEMO = { seek: (i) => demoPlayer && demoPlayer.seek(i, performance.now()), state: () => ({ step: demoStep, book: bookshelf.state }) };
  function demoTick(t) {
    if (!demoPlayer) return;
    if (SHELF_DEMO && demoShelf) {
      const g = demoCanvas.getContext("2d");
      g.putImageData(demoShelf, demoShift, 0);
    }
    if (t - demoLastDet < 33) return;
    demoLastDet = t;
    const frame = demoPlayer.at(t, canvas.width, canvas.height);
    if (frame.step !== demoStep) {
      demoStep = frame.step;
      if (frame.label) caption(frame.label, "demo");
      if (SHELF_DEMO && frame.step === 0) calib.startScan(false);
    }
    processHands(frame.hands.map((h) => h.lm), t, false);
  }

  // ------------------------------------------------------------ cizim dongusu
  let lastT = performance.now(), fpsAcc = 0, fpsN = 0;
  function frame() {
    const t = performance.now();
    const dt = Math.min(0.05, (t - lastT) / 1000);
    lastT = t;
    fpsAcc += dt; fpsN++;
    if (fpsAcc > 0.5) { st.fps = fpsN / fpsAcc; fpsAcc = 0; fpsN = 0; updatePills(); }
    if (DEMO) demoTick(t);
    if (st.thinking && (t - st.thinkingT > 20000)) setThinking(false);
    const t0 = performance.now();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (st.active) {
      continuous(hands, t, dt);
      controls(hands, t);
      bookshelf.update(hands, t, dt);
      for (const h of hands) h.events = []; // olaylar (savurma, itme) tek kez islenir
      particles.update(dt); fire.update(dt); seal.update(dt, t); planets.update(dt, canvas.width, canvas.height);
      burst.update(dt); lightning.update(dt); trail.update(t); face.update(t);
      const [sx, sy] = burst.offset();
      ctx.setTransform(1, 0, 0, 1, sx, sy);
      document.body.style.setProperty("--shake", `translate(${sx}px, ${sy}px)`);
      trail.draw(ctx, t);
      seal.draw(ctx, t);
      planets.draw(ctx, particles.quality);
      particles.draw(ctx);
      fire.draw(ctx);
      lightning.draw(ctx);
      burst.draw(ctx);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      if (settings.get("yuz")) face.draw(ctx, t);
      calib.draw(ctx, t);      // tarama/ayar katmani kitabin altinda kalsin
      bookshelf.draw(ctx, t);
      for (const r of rings) JEL.drawHoldRing(ctx, r);
      if (st.skeleton) drawSkeleton(ctx, hands);
      if (!DEMO && settings.get("kitaplik") && bookshelf.hasShelf() && app.source()) {
        q("#warn").classList.toggle("show", drift.check(app.source(), t));
      }
      if (DEMO && SHELF_DEMO) q("#warn").classList.toggle("show", drift.check(demoCanvas, t));
    }
    // performans butcesi: kare uzarsa parcacik sayisini azalt
    st.drawMs = st.drawMs * 0.9 + (performance.now() - t0) * 0.1;
    const frameMs = 1000 / Math.max(1, st.fps);
    particles.quality = Math.max(0.3, Math.min(1, particles.quality + (frameMs > 33 || st.drawMs > 14 ? -0.02 : 0.01)));
    requestAnimationFrame(frame);
  }

  const BONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
    [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17]];
  function drawSkeleton(g, hs) {
    g.save(); g.strokeStyle = "rgba(52,227,240,0.8)"; g.fillStyle = "#e6fbff"; g.lineWidth = 2;
    g.font = "600 12px Rajdhani, sans-serif";
    for (const h of hs) {
      g.beginPath();
      for (const [a, b] of BONES) { g.moveTo(h.lm[a].x, h.lm[a].y); g.lineTo(h.lm[b].x, h.lm[b].y); }
      g.stroke();
      for (const p of h.lm) { g.beginPath(); g.arc(p.x, p.y, 3, 0, Math.PI * 2); g.fill(); }
      g.fillText(`${h.pose} · ${h.f.pinch.toFixed(2)}`, h.lm[0].x + 10, h.lm[0].y + 18);
    }
    g.restore();
  }

  function updatePills() {
    q("#pFps").textContent = `${st.fps.toFixed(0)} FPS`;
    q("#pHands").textContent = `✋ ${st.handsN}`;
    q("#pDet").textContent = `${st.detMs.toFixed(0)} ms`;
  }

  function resize() {
    // DPR en fazla 1: efektler zaten yumusak, piksel maliyeti dusuk kalsin
    canvas.width = innerWidth; canvas.height = innerHeight;
  }

  // ------------------------------------------------------------ ac / kapat
  function setActive(on) {
    st.active = on;
    document.body.classList.toggle("off", !on);
    if (on) { startCamera(); toast("El Kontrolü açık"); }
    else {
      stopCamera(); hands = []; holds.reset(); face.reset(); seal.clear(); trail.clear();
      bookshelf.putBack(); calib.toggle(false);
    }
  }

  // ------------------------------------------------------------ olaylar (SSE)
  function connectSSE() {
    const url = withKey("/api/events" + (DEMO ? "" : "?client=el"));
    const es = new EventSource(url);
    es.onmessage = (m) => {
      let e;
      try { e = JSON.parse(m.data); } catch (err) { return; }
      const d = e.data;
      if (e.kind === "snapshot") { st.speaking = !!(d && d.speaking); return; }
      if (e.kind === "engine_state") {
        st.speaking = d === "speaking";
        if (st.speaking) setThinking(false);
      }
      if (e.kind === "transcript" && d) {
        if (d.who === "cyraen") { caption(d.text, "cyraen"); setThinking(false); }
        else if (d.who === "user" && d.source !== "el") caption(d.text, "user");
      }
      if (DEMO) return;
      if (e.kind === "el.control" && d) {
        if (d.islem === "ac") setActive(true);
        if (d.islem === "kapat") setActive(false);
        if (d.islem === "eldeki") { if (!st.active) setActive(true); setTimeout(readHeldBook, st.active ? 300 : 2500); }
        if (d.islem === "tara") { if (!st.active) setActive(true); calib.toggle(true); setTimeout(() => calib.startScan(false), 1200); }
      }
      if (e.kind === "el.gezegen" && d && d.ad) {
        const pl = planets.planets.filter((p) => p.state !== "explode").pop();
        if (pl) planets.morph(pl, d.ad); else { st.pendingPlanet = d.ad; toast(`Sıradaki çimdik: ${JEL.PLANET_NAMES[d.ad]}`); }
      }
      if (e.kind === "kitaplik.tarama") calib.onScanEvent(d);
      if (e.kind === "kitaplik.degisti") reload();
    };
    es.onerror = () => { q("#pConn").classList.add("bad"); };
    es.onopen = () => { q("#pConn").classList.remove("bad"); };
  }

  // ------------------------------------------------------------ tuslar
  window.addEventListener("keydown", (e) => {
    if (document.activeElement && document.activeElement.tagName === "INPUT") return;
    audio.unlock();
    const k = e.key.toLowerCase();
    if (k === "escape") { if (calib.active) calib.toggle(false); else setActive(false); }
    else if (k === "h") setActive(!st.active);
    else if (k === "l") { st.ui = !st.ui; document.body.classList.toggle("clean", !st.ui); }
    else if (k === "e") q("#fxPanel").classList.toggle("show");
    else if (k === "f") { settings.set("yuz", !settings.get("yuz")); toast("Yüz kilidi " + (settings.get("yuz") ? "açık" : "kapalı")); }
    else if (k === "k") calib.toggle();
    else if (k === "d") st.skeleton = !st.skeleton;
    else if (k === "m") { settings.set("sesler", !settings.get("sesler")); toast("Efekt sesleri " + (settings.get("sesler") ? "açık" : "kapalı")); }
    else if (k === "c") nextCamera();
    else if (k === "b") readHeldBook();
    else if (k === "j" && DEMO) { demoShift = demoShift ? 0 : 140; drift.forced = false; toast(demoShift ? "Demo: kamera kıpırdatıldı" : "Demo: kamera yerinde"); }
  });
  window.addEventListener("pointerdown", () => audio.unlock());

  // ------------------------------------------------------------ yuz kilidi sesi
  const welcome = new Audio();
  welcome.preload = "auto";
  face.onLocked = () => {
    if (settings.get("sesler")) audio.lock();
    const t = performance.now();
    if (DEMO || t - st.lastWelcome < 60000 || st.speaking || st.thinking) return;
    st.lastWelcome = t;
    welcome.currentTime = 0;
    welcome.play().catch(() => { /* kullanici etkilesimi yoksa tarayici engeller */ });
  };

  // ------------------------------------------------------------ baslat
  async function main() {
    resize();
    addEventListener("resize", resize);
    settings.render(q("#fxPanel"));
    q("#btnFx").addEventListener("click", () => q("#fxPanel").classList.toggle("show"));
    q("#btnShelf").addEventListener("click", () => calib.toggle());
    q("#btnHeld").addEventListener("click", () => readHeldBook());
    q("#btnOn").addEventListener("click", () => setActive(true));
    if (!DEMO) welcome.src = withKey("/api/el/hosgeldin.mp3");
    connectSSE();
    setupDemo();
    await reload();
    requestAnimationFrame(frame);
    if (DEMO) return;
    await startCamera();
    await loadVision();
    const sched = new JEL.FrameScheduler(video, [
      { name: "el", hz: 30, run: detectHands },
      { name: "yuz", hz: 5, run: detectFaces },
    ]);
    sched.start();
    if (params.get("eldeki") === "1") setTimeout(readHeldBook, 2500);
    if (params.get("tara") === "1") { calib.toggle(true); setTimeout(() => calib.startScan(false), 1500); }
  }
  main().catch((e) => { console.error(e); toast("Başlatılamadı: " + e); });
})();
