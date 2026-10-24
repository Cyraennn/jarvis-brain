// El Kontrolu demo: sentetik el iskeletleri (?el=demo) + prosedurel kitaplik (&kitaplik=1).
// makeHand testlerde de kullanilir (gercekci 21 nokta, ekran pikselinde).
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.JarvisDemoHands = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // yerel el uzayi: bilek (0,0), parmaklar -y yonunde, birim = bilek->orta kok
  const MCP = { index: [-0.32, -0.92], middle: [0, -1], ring: [0.28, -0.95], pinky: [0.52, -0.82] };
  const LEN = { index: [0.45, 0.27, 0.22], middle: [0.5, 0.3, 0.24], ring: [0.46, 0.28, 0.22], pinky: [0.36, 0.22, 0.2] };
  const FAN = { index: -0.12, middle: -0.02, ring: 0.08, pinky: 0.2 };
  const ORDER = ["index", "middle", "ring", "pinky"];

  function finger(name, mode) {
    const [mx, my] = MCP[name];
    const [l1, l2, l3] = LEN[name];
    const a = FAN[name];
    const ux = Math.sin(a), uy = -Math.cos(a);
    if (mode === "open") {
      return [[mx, my], [mx + ux * l1, my + uy * l1], [mx + ux * (l1 + l2), my + uy * (l1 + l2)],
        [mx + ux * (l1 + l2 + l3), my + uy * (l1 + l2 + l3)]];
    }
    // kivrik: PIP biraz ileri, DIP ve uc avuca geri katlanir (uc ~ MCP hizasi)
    const p = [mx + ux * l1 * 0.55, my + uy * l1 * 0.55];
    const d = [p[0] + ux * 0.02, p[1] + 0.15];
    const t = [d[0] - ux * 0.02, d[1] + 0.1];
    return [[mx, my], p, d, t];
  }

  // pose: open | fist | point | victory | thumbs_up | pinch
  function localHand(pose) {
    const pts = new Array(21);
    pts[0] = [0, 0];
    const modes = {
      open: ["open", "open", "open", "open"], fist: ["curl", "curl", "curl", "curl"],
      point: ["open", "curl", "curl", "curl"], victory: ["open", "open", "curl", "curl"],
      thumbs_up: ["curl", "curl", "curl", "curl"], pinch: ["half", "open", "open", "open"],
    }[pose] || ["open", "open", "open", "open"];
    ORDER.forEach((name, i) => {
      const base = 5 + i * 4;
      let f;
      if (modes[i] === "half") f = [[-0.32, -0.92], [-0.38, -1.25], [-0.47, -1.35], [-0.55, -1.22]];
      else f = finger(name, modes[i]);
      for (let k = 0; k < 4; k++) pts[base + k] = f[k];
    });
    // basparmak
    if (pose === "open") pts.splice(1, 4, [-0.25, -0.25], [-0.5, -0.45], [-0.68, -0.62], [-0.84, -0.78]);
    else if (pose === "thumbs_up") pts.splice(1, 4, [-0.25, -0.3], [-0.4, -0.65], [-0.45, -1.05], [-0.42, -1.55]);
    else if (pose === "pinch") pts.splice(1, 4, [-0.25, -0.25], [-0.45, -0.55], [-0.52, -0.9], [-0.55, -1.2]);
    else pts.splice(1, 4, [-0.22, -0.25], [-0.32, -0.5], [-0.2, -0.68], [-0.1, -0.75]);
    return pts;
  }

  // Ekran pikselinde 21 nokta. opts: {x, y (bilek), size, roll (rad), facing (0-1), z}
  function makeHand(pose, opts) {
    const o = Object.assign({ x: 400, y: 500, size: 120, roll: 0, facing: 1, z: 0 }, opts || {});
    const c = Math.cos(o.roll), s = Math.sin(o.roll);
    return localHand(pose).map(([u, v]) => {
      const uu = u * o.facing;
      return { x: o.x + (uu * c - v * s) * o.size, y: o.y + (uu * s + v * c) * o.size, z: o.z };
    });
  }

  // ------------------------------------------------------------ demo senaryosu
  // Her adim: [sure ms, ad, (t 0-1, W, H) -> [{pose, x, y, size, roll, facing}]]
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = (t) => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

  function effectScript() {
    return [
      [2600, "Açık el: ateş", (t, W, H) => [{ pose: "open", x: lerp(W * 0.35, W * 0.6, ease(t)), y: H * 0.78, size: H * 0.2, roll: Math.sin(t * 6) * 0.15 }]],
      [3200, "İki açık el: mühür halkaları", (t, W, H) => [
        { pose: "open", x: W * 0.3, y: H * 0.8, size: H * 0.19, facing: lerp(1, 0.35, Math.max(0, Math.sin(t * Math.PI))) },
        { pose: "open", x: W * 0.7, y: H * 0.8, size: H * 0.19, roll: 0.1 }]],
      [800, "Çimdik: gezegen", (t, W, H) => [{ pose: "pinch", x: W * 0.5, y: H * 0.8, size: H * 0.2 }]],
      [3000, "Gezegeni taşı ve çevir", (t, W, H) => [{ pose: "pinch", x: lerp(W * 0.5, W * 0.62, ease(t)), y: lerp(H * 0.8, H * 0.7, ease(t)), size: H * 0.2, roll: Math.sin(t * 4) * 0.5 }]],
      [2400, "İki elle büyüt", (t, W, H) => [
        { pose: "pinch", x: lerp(W * 0.56, W * 0.42, ease(t)), y: H * 0.72, size: H * 0.2 },
        { pose: "pinch", x: lerp(W * 0.66, W * 0.82, ease(t)), y: H * 0.72, size: H * 0.2 }]],
      [600, "Bırak: süzülür", (t, W, H) => [{ pose: "open", x: W * 0.42, y: H * 0.78, size: H * 0.2 }]],
      [1200, "", (t, W, H) => []],
      [700, "Yumruk", (t, W, H) => [{ pose: "fist", x: W * 0.5, y: H * 0.8, size: H * 0.2 }]],
      [1600, "Hızla aç: patlat", (t, W, H) => [{ pose: "open", x: W * 0.5, y: H * 0.8, size: H * 0.2 }]],
      [3000, "İki işaret: şimşek", (t, W, H) => [
        { pose: "point", x: W * 0.3, y: lerp(H * 0.8, H * 0.7, Math.sin(t * 9) * 0.5 + 0.5), size: H * 0.2 },
        { pose: "point", x: W * 0.7, y: H * 0.8, size: H * 0.2 }]],
      [3200, "İşaret: ışık izi", (t, W, H) => [{ pose: "point", x: W * 0.5 + Math.cos(t * 7) * W * 0.18, y: H * 0.75 + Math.sin(t * 14) * H * 0.12, size: H * 0.2 }]],
      [1600, "👍 basılı tut (demoda komut gitmez)", (t, W, H) => [{ pose: "thumbs_up", x: W * 0.5, y: H * 0.82, size: H * 0.2 }]],
      [1400, "✌️ zafer", (t, W, H) => [{ pose: "victory", x: W * 0.5, y: H * 0.82, size: H * 0.2 }]],
      [1500, "", (t, W, H) => []],
    ];
  }

  // Kitaplik demosu: sirtlar ekranda (aynali) konumlanir; adimlar el ile raf arasinda gezinir.
  // target(id) -> {x, y} (sirtin ekran merkezi) disaridan verilir.
  function shelfScript(target) {
    // hedef: isaret ucu (point) ya da cimdik noktasi (pinch) sirtin uzerine gelsin -> bilegi buna gore kaydir
    const tipOff = (pose, size) => {
      const lm = makeHand(pose, { x: 0, y: 0, size });
      return pose === "pinch" ? { x: (lm[4].x + lm[8].x) / 2, y: (lm[4].y + lm[8].y) / 2 } : lm[8];
    };
    const at = (id, W, H, pose, size) => {
      const p = target(id) || { x: W / 2, y: H / 2 };
      const o = tipOff(pose || "point", size || H * 0.16);
      return { x: p.x - o.x, y: p.y + H * 0.1 - o.y };
    };
    return [
      [3200, "Kitaplık taranıyor", (t, W, H) => []],
      [2200, "İşaret ucunu sırta getir", (t, W, H) => { const a = at(2, W, H), b = at(5, W, H); return [{ pose: "point", x: lerp(a.x, b.x, ease(t)), y: lerp(a.y, b.y, ease(t)), size: H * 0.16 }]; }],
      [900, "Seç", (t, W, H) => { const b = at(5, W, H); return [{ pose: "point", x: b.x, y: b.y, size: H * 0.16 }]; }],
      [700, "Çimdikle tut", (t, W, H) => { const b = at(5, W, H, "pinch"); return [{ pose: "pinch", x: b.x, y: b.y, size: H * 0.16 }]; }],
      [1100, "Kendine çek", (t, W, H) => { const b = at(5, W, H, "pinch"); return [{ pose: "pinch", x: lerp(b.x, W * 0.5, ease(t)), y: lerp(b.y, H * 1.05, ease(t)), size: lerp(H * 0.16, H * 0.24, t) }]; }],
      [1800, "Kapak", (t, W, H) => [{ pose: "open", x: W * 0.5, y: H * 1.05, size: H * 0.2 }]],
      [3200, "Holografik sayfalar", (t, W, H) => []],
      [700, "Savur: sonraki sayfa", (t, W, H) => [{ pose: "open", x: lerp(W * 0.75, W * 0.2, ease(t)), y: H * 0.85, size: H * 0.2 }]],
      [2200, "", (t, W, H) => []],
      [1500, "👍 özet (demoda okunmaz)", (t, W, H) => [{ pose: "thumbs_up", x: W * 0.78, y: H * 0.88, size: H * 0.2 }]],
      [1600, "✊ rafa geri koy", (t, W, H) => [{ pose: "fist", x: W * 0.78, y: H * 0.88, size: H * 0.2 }]],
      [2400, "", (t, W, H) => []],
    ];
  }

  class ScriptPlayer {
    constructor(script) {
      this.script = script;
      this.total = script.reduce((a, s) => a + s[0], 0);
      this.t0 = null;
    }
    // adima atla (test/cekim icin): window.JEL_DEMO.seek(i)
    seek(step, now) {
      let off = 0;
      for (let i = 0; i < Math.min(step, this.script.length); i++) off += this.script[i][0];
      this.t0 = now - off;
    }

    // -> {hands: [{lm, pose}], step, label, t}
    at(now, W, H) {
      if (this.t0 === null) this.t0 = now;
      let t = (now - this.t0) % this.total;
      for (let i = 0; i < this.script.length; i++) {
        const [d, label, fn] = this.script[i];
        if (t < d) {
          const specs = fn(t / d, W, H) || [];
          return { step: i, label, t: t / d, hands: specs.map((sp) => ({ lm: makeHand(sp.pose, sp), pose: sp.pose })) };
        }
        t -= d;
      }
      return { step: -1, label: "", t: 0, hands: [] };
    }
  }

  // ------------------------------------------------------------ prosedurel kitaplik
  const DEMO_TITLES = [
    ["Otostopçunun Galaksi Rehberi", "Adams"], ["Mülksüzler", "Le Guin"], ["Davranış", "Sapolsky"],
    ["Tahıla Karşı", "Scott"], ["Oblomov", "Gonçarov"], ["Dune", "Herbert"], ["Simyacı", "Coelho"],
    ["Sapiens", "Harari"], ["Kürk Mantolu Madonna", "Sabahattin Ali"], ["Suç ve Ceza", "Dostoyevski"],
    ["1984", "Orwell"], ["Körlük", "Saramago"], ["Yabancı", "Camus"], ["Saatleri Ayarlama Enstitüsü", "Tanpınar"],
    ["Bülbülü Öldürmek", "Lee"], ["Fahrenheit 451", "Bradbury"], ["Dönüşüm", "Kafka"], ["Uçurtma Avcısı", "Hosseini"],
  ];
  const SPINE_COLORS = ["#7a2e2e", "#2e4a7a", "#3f6b3a", "#b48a3c", "#5a3a6e", "#24585c", "#8c5a2b",
    "#2b2b2b", "#a33f2b", "#cfc6b0", "#3b4f63", "#6e2741"];

  function hash(n) { const x = Math.sin(n * 127.1) * 43758.5453; return x - Math.floor(x); }

  // Ham (aynalanmamis) kareye raf cizer; dogru kutulari dondurur (0-1, ham).
  function drawShelf(ctx, W, H, titles) {
    const list = titles && titles.length ? titles : DEMO_TITLES;
    ctx.fillStyle = "#1c1410"; ctx.fillRect(0, 0, W, H);
    // duvar dokusu
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "#2a211a"); g.addColorStop(1, "#120d0a");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    const shelfX = W * 0.12, shelfW = W * 0.76, rows = 3, top = H * 0.08, rowH = H * 0.26;
    const boxes = [];
    let k = 0;
    for (let r = 0; r < rows; r++) {
      const y0 = top + r * rowH, yb = y0 + rowH * 0.9;
      ctx.fillStyle = "#3b2a1c"; ctx.fillRect(shelfX - 10, yb, shelfW + 20, rowH * 0.1);
      let x = shelfX + 6;
      while (x < shelfX + shelfW - 30 && k < 400) {
        const i = k++;
        const [title, author] = list[i % list.length];
        const w = 22 + hash(i) * 26, h = rowH * (0.62 + hash(i + 9) * 0.26);
        const y = yb - h;
        ctx.fillStyle = SPINE_COLORS[Math.floor(hash(i + 3) * SPINE_COLORS.length)];
        ctx.fillRect(x, y, w, h);
        ctx.fillStyle = "rgba(255,255,255,0.08)"; ctx.fillRect(x + 2, y, 3, h);
        ctx.fillStyle = "rgba(0,0,0,0.35)"; ctx.fillRect(x + w - 3, y, 3, h);
        ctx.save();
        ctx.translate(x + w / 2, y + h / 2); ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = hash(i + 5) > 0.5 ? "#f2e6c8" : "#e8c35a";
        ctx.font = `600 ${Math.min(14, w * 0.5)}px Georgia, serif`;
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(title.length > 26 ? title.slice(0, 25) + "…" : title, 0, 0, h * 0.9);
        ctx.restore();
        boxes.push({ id: "demo" + i, ad: title, yazar: author, kutu: { x: x / W, y: y / H, w: w / W, h: h / H } });
        x += w + 1 + hash(i + 7) * 3;
      }
    }
    return { boxes, raf: { x: shelfX / W, y: top / H, w: shelfW / W, h: (rows * rowH) / H } };
  }

  return { makeHand, localHand, ScriptPlayer, effectScript, shelfScript, drawShelf, DEMO_TITLES };
});
