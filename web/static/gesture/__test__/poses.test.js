// El Kontrolu: durus siniflandirma, basili tutma, koordinat geometrisi - `node poses.test.js`
"use strict";

const path = require("path");
const F = require(path.join(__dirname, "..", "hand-features.js"));
const P = require(path.join(__dirname, "..", "poses.js"));
const C = require(path.join(__dirname, "..", "controller.js"));
const G = require(path.join(__dirname, "..", "shelf-geom.js"));
const D = require(path.join(__dirname, "..", "demo-hands.js"));

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`ok - ${name}`); }
  catch (err) { failed++; console.log(`FAIL - ${name}\n       ${err.message}`); }
}
function assert(c, m) { if (!c) throw new Error(m || "assertion failed"); }
function eq(a, b, m) { if (a !== b) throw new Error(`${m || "not equal"}: expected ${b}, got ${a}`); }
function near(a, b, eps, m) { if (Math.abs(a - b) > (eps || 1e-6)) throw new Error(`${m || "not near"}: expected ${b}, got ${a}`); }

const POSES = ["open", "fist", "point", "victory", "thumbs_up", "pinch"];

// ------------------------------------------------------------ siniflandirma
for (const pose of POSES) {
  test(`rawPose tanir: ${pose}`, () => {
    eq(P.rawPose(F.features(D.makeHand(pose))), pose);
  });
  test(`rawPose donmus/kucuk elde de tanir: ${pose}`, () => {
    eq(P.rawPose(F.features(D.makeHand(pose, { roll: 0.5, size: 60, x: 900, y: 300 }))), pose);
  });
}

test("cimdik histerezisi: esige yakin mesafe cimdikten hemen cikarmaz", () => {
  const lm = D.makeHand("pinch");
  // isaret ucunu basparmaktan el boyunun ~%36'si kadar uzaklastir (enter 0.30 < 0.36 < exit 0.44)
  const s = F.handSize(lm);
  lm[8] = { x: lm[4].x + s * 0.36, y: lm[4].y, z: 0 };
  lm[7] = { x: lm[8].x - s * 0.05, y: lm[8].y - s * 0.12, z: 0 };
  const f = F.features(lm);
  eq(P.rawPose(f, true), "pinch", "cimdikteyken");
  assert(P.rawPose(f, false) !== "pinch", "cimdik disindayken baslamamali");
});

test("yan donmus avuc genisligi azalir (muhur perspektifi)", () => {
  const front = F.palmFacing(D.makeHand("open"));
  const side = F.palmFacing(D.makeHand("open", { facing: 0.35 }));
  assert(front > 0.9 && side < 0.5, `front=${front} side=${side}`);
});

test("roll acisi eli cevirince degisir", () => {
  const a = F.palmRoll(D.makeHand("open"));
  const b = F.palmRoll(D.makeHand("open", { roll: 0.6 }));
  near(b - a, 0.6, 0.05);
});

// ------------------------------------------------------------ PoseTracker
function run(tracker, pose, fromT, ms, opts) {
  let last = null;
  for (let t = fromT; t < fromT + ms; t += 33) last = tracker.update(F.features(D.makeHand(pose, opts)), t);
  return last;
}

test("tracker: durus kararli karelerden sonra gecer", () => {
  const tr = new P.PoseTracker();
  const r1 = tr.update(F.features(D.makeHand("open")), 0);
  eq(r1.pose, "none");
  const r = run(tr, "open", 33, 200);
  eq(r.pose, "open");
});

test("tracker: yumruk -> hizli acik el = burst", () => {
  const tr = new P.PoseTracker();
  run(tr, "fist", 0, 400);
  let burst = false;
  for (let t = 400; t < 700; t += 33) {
    const r = tr.update(F.features(D.makeHand("open")), t);
    if (r.events.some((e) => e.type === "burst")) burst = true;
  }
  assert(burst, "burst bekleniyordu");
});

test("tracker: yavas yumruk -> bekle -> acik el burst degil", () => {
  const tr = new P.PoseTracker();
  run(tr, "fist", 0, 400);
  run(tr, "none", 400, 600, {});
  let burst = false;
  for (let t = 1000; t < 1300; t += 33) {
    const r = tr.update(F.features(D.makeHand("open")), t);
    if (r.events.some((e) => e.type === "burst")) burst = true;
  }
  assert(!burst, "burst beklenmiyordu");
});

test("tracker: acik avuc sola savurma", () => {
  const tr = new P.PoseTracker();
  run(tr, "open", 0, 200, { x: 800 });
  let sw = null;
  for (let i = 0; i < 10; i++) {
    const r = tr.update(F.features(D.makeHand("open", { x: 800 - i * 60 })), 200 + i * 33);
    const e = r.events.find((x) => x.type.startsWith("swipe"));
    if (e) sw = e.type;
  }
  eq(sw, "swipe_left");
});

// ------------------------------------------------------------ HoldController
test("hold: 👍 1 sn tutulunca bir kez tetiklenir, cooldown'da tekrar etmez", () => {
  const hc = new C.HoldController();
  let fired = 0, sawRing = false;
  for (let t = 0; t <= 3000; t += 33) {
    const r = hc.update([{ id: 1, pose: "thumbs_up", x: 0, y: 0 }], {}, t);
    fired += r.fired.length;
    if (r.rings.length) sawRing = true;
  }
  eq(fired, 1);
  assert(sawRing, "ilerleme halkasi gorunmeli");
});

test("hold: duruş bozulunca halka sifirlanir", () => {
  const hc = new C.HoldController();
  for (let t = 0; t < 700; t += 33) hc.update([{ id: 1, pose: "thumbs_up", x: 0, y: 0 }], {}, t);
  for (let t = 700; t < 1000; t += 33) hc.update([{ id: 1, pose: "open", x: 0, y: 0 }], {}, t);
  let fired = 0;
  for (let t = 1000; t < 1600; t += 33) fired += hc.update([{ id: 1, pose: "thumbs_up", x: 0, y: 0 }], {}, t).fired.length;
  eq(fired, 0, "yeniden 1 sn dolmadan tetiklenmemeli");
});

test("hold: ✊ sustur yalniz Jarvis konusurken", () => {
  const hc = new C.HoldController();
  let fired = 0;
  for (let t = 0; t < 2500; t += 33) fired += hc.update([{ id: 1, pose: "fist", x: 0, y: 0 }], { speaking: false }, t).fired.length;
  eq(fired, 0);
  for (let t = 2500; t < 5000; t += 33) fired += hc.update([{ id: 1, pose: "fist", x: 0, y: 0 }], { speaking: true }, t).fired.length;
  eq(fired, 1);
});

test("hold: kapatilan kontrol tetiklenmez", () => {
  const hc = new C.HoldController();
  let fired = 0;
  for (let t = 0; t < 2000; t += 33) fired += hc.update([{ id: 1, pose: "victory", x: 0, y: 0 }], { disabled: new Set(["victory"]) }, t).fired.length;
  eq(fired, 0);
});

// ------------------------------------------------------------ geometri
const T = G.coverTransform(1280, 720, 1000, 1000); // 16:9 video, kare ekran -> yanlardan kirpilir

test("cover: olcek ve kayma", () => {
  near(T.s, 1000 / 720, 1e-9);
  near(T.ox, (1000 - 1280 * T.s) / 2, 1e-9);
  near(T.oy, 0, 1e-9);
});

test("ham <-> ekran ayna donusumu tersinir", () => {
  const p = G.rawToScreen(T, 0.3, 0.6);
  const r = G.screenToRaw(T, p.x, p.y);
  near(r.x, 0.3, 1e-9); near(r.y, 0.6, 1e-9);
  assert(G.rawToScreen(T, 0.2, 0).x > G.rawToScreen(T, 0.8, 0).x, "ayna: ham soldaki ekranda sagda");
});

test("kutu ekrana aynali cizilir ve geri cevrilir", () => {
  const box = { x: 0.40, y: 0.2, w: 0.05, h: 0.3 };
  const rect = G.boxToScreen(T, box);
  const left = G.rawToScreen(T, 0.45, 0.2).x; // ham sag kenar = ekran sol kenar
  near(rect.x, left, 1e-6);
  const back = G.screenRectToBox(T, rect);
  near(back.x, 0.40, 1e-9); near(back.w, 0.05, 1e-9); near(back.h, 0.3, 1e-9);
});

test("kirpma ham piksellerde ve sinirda", () => {
  const c = G.cropRect({ x: 0.98, y: 0.5, w: 0.05, h: 0.6 }, 1280, 720);
  assert(c.sx + c.sw <= 1280 && c.sy + c.sh <= 720, JSON.stringify(c));
  eq(c.sx, Math.floor(0.98 * 1280));
});

test("sirt secimi: en yakin + histerezis", () => {
  const items = [
    { id: "a", rect: { x: 100, y: 100, w: 30, h: 200 } },
    { id: "b", rect: { x: 132, y: 100, w: 30, h: 200 } },
  ];
  eq(G.pickSpine(items, { x: 112, y: 320 }).item.id, "a", "uc sirtin altinda da secilir");
  // a seciliyken sinira yakin ama b'ye cok az yakin -> a kalir
  eq(G.pickSpine(items, { x: 132, y: 200 }, { current: "a" }).item.id, "a");
  // belirgin yaklasinca b
  eq(G.pickSpine(items, { x: 150, y: 200 }, { current: "a" }).item.id, "b");
  eq(G.pickSpine(items, { x: 600, y: 600 }).item, null, "cok uzak: secim yok");
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
