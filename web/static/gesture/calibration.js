(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) {
    module.exports = factory(require("./gesture-engine.js"));
  } else {
    root.CyraenCalibration = factory(root.CyraenGestureEngine);
  }
})(typeof self !== "undefined" ? self : this, function (GestureEngineModule) {
  "use strict";

  const { dist, isFingerCurled, DEFAULT_CONFIG } = GestureEngineModule;
  const STORAGE_KEY = "cyraen_gesture_calibration_v1";
  const WRIST = 0, THUMB_TIP = 4, INDEX_TIP = 8;
  const FINGERS = [
    { mcp: 5, pip: 6, tip: 8 },
    { mcp: 9, pip: 10, tip: 12 },
    { mcp: 13, pip: 14, tip: 16 },
    { mcp: 17, pip: 18, tip: 20 },
  ];

  function safeLocalStorage() {
    try {
      return typeof localStorage !== "undefined" ? localStorage : null;
    } catch (e) {
      return null;
    }
  }

  function loadCalibration() {
    const ls = safeLocalStorage();
    if (!ls) return null;
    try {
      const raw = ls.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function saveCalibration(config) {
    const ls = safeLocalStorage();
    if (!ls) return;
    try {
      ls.setItem(STORAGE_KEY, JSON.stringify(config));
    } catch (e) {
      /* private mode / quota - calibration just won't persist */
    }
  }

  function clearCalibration() {
    const ls = safeLocalStorage();
    if (ls) {
      try {
        ls.removeItem(STORAGE_KEY);
      } catch (e) {}
    }
  }

  function stddev(values) {
    if (values.length < 2) return 0;
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    const variance = values.reduce((a, b) => a + (b - mean) * (b - mean), 0) / values.length;
    return Math.sqrt(variance);
  }

  function computeThresholds(pinchSamples, palmZSamples) {
    const cfg = { calibratedAt: Date.now() };
    if (pinchSamples.length >= 10) {
      const minD = Math.min(...pinchSamples);
      const maxD = Math.max(...pinchSamples);
      const range = maxD - minD;
      if (range > 0.02) {
        cfg.pinchCloseDist = Math.max(0.02, minD + range * 0.3);
        cfg.pinchOpenDist = Math.min(0.2, minD + range * 0.45);
      }
    }
    if (palmZSamples.length >= 5) {
      const spread = stddev(palmZSamples);
      cfg.explodeZDelta = -Math.max(0.04, spread * 2.5);
    }
    return Object.assign({}, DEFAULT_CONFIG, cfg, { oneEuro: DEFAULT_CONFIG.oneEuro });
  }

  // Samples ~10s of user-driven pinch / open-palm gestures via `getLandmarks()`
  // (a callback into the live detection loop; calibration never touches the
  // webcam or MediaPipe itself) and derives personal thresholds from them.
  function runCalibration({ getLandmarks, durationMs = 10000, onProgress, sampleIntervalMs = 40 }) {
    return new Promise((resolve) => {
      const pinchSamples = [];
      const palmZSamples = [];
      const startedAt = Date.now();

      const tick = () => {
        const elapsed = Date.now() - startedAt;
        const hands = getLandmarks ? getLandmarks() : null;
        if (hands && hands.length) {
          const lm = hands[0];
          pinchSamples.push(dist(lm[THUMB_TIP], lm[INDEX_TIP]));
          const allOpen = FINGERS.every((f) => !isFingerCurled(lm, f, lm[WRIST], DEFAULT_CONFIG.curlRatio));
          if (allOpen) palmZSamples.push(lm[WRIST].z || 0);
        }
        if (onProgress) onProgress(Math.min(1, elapsed / durationMs));

        if (elapsed >= durationMs) {
          const config = computeThresholds(pinchSamples, palmZSamples);
          saveCalibration(config);
          resolve({ config, pinchSamples: pinchSamples.length, palmZSamples: palmZSamples.length });
          return;
        }
        setTimeout(tick, sampleIntervalMs);
      };
      tick();
    });
  }

  return { runCalibration, loadCalibration, saveCalibration, clearCalibration, computeThresholds, STORAGE_KEY };
});
