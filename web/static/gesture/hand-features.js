// El Kontrolu: MediaPipe 21 noktalik el iskeletinden olculer (saf fonksiyonlar, Node'da test edilir).
// Noktalar EKRAN uzayinda verilir ({x, y} piksel, z goreli): mesafeler izotropik olsun.
//   0 bilek · 1-4 basparmak · 5-8 isaret · 9-12 orta · 13-16 yuzuk · 17-20 serce
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.JarvisHandFeatures = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const FINGERS = {
    index: [5, 6, 7, 8],
    middle: [9, 10, 11, 12],
    ring: [13, 14, 15, 16],
    pinky: [17, 18, 19, 20],
  };
  const TIPS = [4, 8, 12, 16, 20];

  function dist(a, b) {
    const dx = a.x - b.x, dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function dist3(a, b) {
    const dx = a.x - b.x, dy = a.y - b.y, dz = (a.z || 0) - (b.z || 0);
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  // Elin olcegi: bilek -> orta parmak koku. Tum esikler buna gore normalize edilir.
  function handSize(lm) {
    return Math.max(1e-6, dist(lm[0], lm[9]));
  }

  // 0 = tamamen kivrik, 1 = tamamen acik. Uc bilege, PIP ekleminden ne kadar uzak?
  function fingerExtension(lm, name) {
    const [mcp, pip, , tip] = FINGERS[name];
    const w = lm[0];
    const tipD = dist(lm[tip], w), pipD = dist(lm[pip], w), mcpD = dist(lm[mcp], w);
    // acik parmakta uc, PIP'ten belirgin uzaktir; kivrikta MCP'ye yakindir
    // acik: ~2.5 (uc PIP'in cok otesinde), kivrik: <= ~0.3
    const ratio = (tipD - mcpD) / Math.max(1e-6, Math.abs(pipD - mcpD));
    return Math.max(0, Math.min(1, (ratio - 0.6) / 1.4));
  }

  function thumbExtension(lm) {
    const size = handSize(lm);
    // basparmak ucu isaret parmagi kokunden uzak ve bilekten IP ekleminden uzaksa acik
    const away = dist(lm[4], lm[5]) / size;
    const straight = dist(lm[4], lm[0]) > dist(lm[3], lm[0]) * 1.05;
    return Math.max(0, Math.min(1, (away - 0.35) / 0.45)) * (straight ? 1 : 0.4);
  }

  function pinchDistance(lm) {
    return dist(lm[4], lm[8]) / handSize(lm);
  }

  function palmCenter(lm) {
    const ids = [0, 5, 9, 13, 17];
    let x = 0, y = 0, z = 0;
    for (const i of ids) { x += lm[i].x; y += lm[i].y; z += lm[i].z || 0; }
    return { x: x / ids.length, y: y / ids.length, z: z / ids.length };
  }

  function pinchPoint(lm) {
    return { x: (lm[4].x + lm[8].x) / 2, y: (lm[4].y + lm[8].y) / 2, z: ((lm[4].z || 0) + (lm[8].z || 0)) / 2 };
  }

  // Elin ekran duzlemindeki donusu (isaret koku -> serce koku dogrultusu), radyan.
  function palmRoll(lm) {
    return Math.atan2(lm[17].y - lm[5].y, lm[17].x - lm[5].x);
  }

  // Avuc genisligi / boy: el yana cevrildikce kucur (~cos(yaw)). Muhur/halka perspektifi icin.
  function palmFacing(lm) {
    const width = dist(lm[5], lm[17]);
    const len = handSize(lm);
    return Math.max(0.12, Math.min(1, (width / len) / 0.82));
  }

  // Elin "yukari" yonu (bilek -> orta kok), ekran acisi.
  function palmUpAngle(lm) {
    return Math.atan2(lm[9].y - lm[0].y, lm[9].x - lm[0].x);
  }

  function features(lm) {
    const ext = {
      thumb: thumbExtension(lm),
      index: fingerExtension(lm, "index"),
      middle: fingerExtension(lm, "middle"),
      ring: fingerExtension(lm, "ring"),
      pinky: fingerExtension(lm, "pinky"),
    };
    const size = handSize(lm);
    const thumbTip = lm[4];
    // basparmak yukari: uc bilegin ve isaret kokunun belirgin ustunde (ekranda y kucuk)
    const thumbUp = (lm[5].y - thumbTip.y) / size;
    return {
      size,
      ext,
      pinch: pinchDistance(lm),
      palm: palmCenter(lm),
      pinchPt: pinchPoint(lm),
      roll: palmRoll(lm),
      facing: palmFacing(lm),
      upAngle: palmUpAngle(lm),
      thumbUp,
      tips: TIPS.map((i) => lm[i]),
      indexTip: lm[8],
    };
  }

  return { FINGERS, TIPS, dist, dist3, handSize, fingerExtension, thumbExtension, pinchDistance,
    palmCenter, pinchPoint, palmRoll, palmFacing, palmUpAngle, features };
});
