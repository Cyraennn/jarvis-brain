(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) {
    module.exports = factory(require("./smoothing.js"));
  } else {
    root.CyraenGestureEngine = factory(root.CyraenSmoothing);
  }
})(typeof self !== "undefined" ? self : this, function (Smoothing) {
  "use strict";

  const { FilteredPoint } = Smoothing;

  // MediaPipe HandLandmarker indices.
  const WRIST = 0;
  const THUMB_TIP = 4;
  const INDEX_MCP = 5, INDEX_PIP = 6, INDEX_TIP = 8;
  const MIDDLE_MCP = 9, MIDDLE_PIP = 10, MIDDLE_TIP = 12;
  const RING_MCP = 13, RING_PIP = 14, RING_TIP = 16;
  const PINKY_MCP = 17, PINKY_PIP = 18, PINKY_TIP = 20;

  const FINGERS = [
    { mcp: INDEX_MCP, pip: INDEX_PIP, tip: INDEX_TIP },
    { mcp: MIDDLE_MCP, pip: MIDDLE_PIP, tip: MIDDLE_TIP },
    { mcp: RING_MCP, pip: RING_PIP, tip: RING_TIP },
    { mcp: PINKY_MCP, pip: PINKY_PIP, tip: PINKY_TIP },
  ];

  function dist(a, b) {
    const dx = a.x - b.x, dy = a.y - b.y, dz = (a.z || 0) - (b.z || 0);
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  function mid(a, b) {
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: ((a.z || 0) + (b.z || 0)) / 2 };
  }

  // A curled finger folds its tip back past its own pip joint, so tip-to-wrist
  // distance drops below pip-to-wrist distance; comparing against the pip
  // (not the base/mcp) gives a wide, scale- and orientation-independent
  // margin - an extended finger's tip is typically 1.4-2x farther from the
  // wrist than its pip, while a curled one folds back to at or inside it.
  function isFingerCurled(landmarks, finger, wrist, curlRatio) {
    const tipDist = dist(landmarks[finger.tip], wrist);
    const pipDist = dist(landmarks[finger.pip], wrist);
    return tipDist < pipDist * curlRatio;
  }

  const DEFAULT_CONFIG = {
    pinchCloseDist: 0.055,
    pinchOpenDist: 0.075,
    curlRatio: 0.9,
    selectDwellMs: 400,
    selectStabilityRadius: 0.03,
    explodeZDelta: -0.06,
    explodeCooldownMs: 900,
    deadZone: 0.008,
    oneEuro: { minCutoff: 1.0, beta: 0.007, dCutoff: 1.0 },
  };

  function makeHandState(cfg) {
    return {
      pinching: false,
      filtPinchCenter: new FilteredPoint(cfg.oneEuro),
      prevPinchCenter: null,
      pinchCenter: null,
      openPalm: false,
      explodeBaselineZ: null,
      pointing: false,
      filtPoint: new FilteredPoint(cfg.oneEuro),
      dwellAnchor: null,
      dwellStart: null,
      selectFired: false,
      fist: false,
      wasFist: false,
    };
  }

  class GestureEngine {
    constructor(config) {
      const { onIntent, ...rest } = config || {};
      this.cfg = Object.assign({}, DEFAULT_CONFIG, rest, {
        oneEuro: Object.assign({}, DEFAULT_CONFIG.oneEuro, rest.oneEuro),
      });
      // The engine never touches the scene itself - it only classifies
      // landmarks and pushes semantic intents out through this callback
      // (in addition to returning them from processFrame for callers that
      // prefer to pull, e.g. tests and the debug panel).
      this._onIntent = typeof onIntent === "function" ? onIntent : null;
      this._hands = [];
      this._handCount = 0;
      this._locked = false;
      this._twoHandPrevDist = null;
      this._lastExplodeTs = -Infinity;
    }

    configure(partial) {
      Object.assign(this.cfg, partial);
      if (partial && partial.oneEuro) {
        Object.assign(this.cfg.oneEuro, partial.oneEuro);
        for (const st of this._hands) {
          st.filtPinchCenter.configure(this.cfg.oneEuro);
          st.filtPoint.configure(this.cfg.oneEuro);
        }
      }
    }

    isLocked() {
      return this._locked;
    }

    _notify(intent, intents) {
      intents.push(intent);
      if (this._onIntent) this._onIntent(intent);
    }

    // Hand count changing (a hand appears/disappears) drops all per-hand
    // filter/dwell state so the model freezes instead of jumping on return.
    reset() {
      this._hands = [];
      this._handCount = 0;
      this._twoHandPrevDist = null;
    }

    processFrame(handsLandmarks, timestampMs) {
      const intents = [];
      if (!handsLandmarks || handsLandmarks.length === 0) {
        this.reset();
        return intents;
      }

      if (handsLandmarks.length !== this._handCount) {
        this.reset();
        this._handCount = handsLandmarks.length;
      }
      while (this._hands.length < handsLandmarks.length) {
        this._hands.push(makeHandState(this.cfg));
      }

      const states = handsLandmarks.map((lm, i) => this._observeHand(this._hands[i], lm, timestampMs));

      for (const st of states) {
        if (st.fist && !st.wasFist) {
          this._locked = !this._locked;
          this._notify({ type: "lock", locked: this._locked, ts: timestampMs }, intents);
        }
        st.wasFist = st.fist;
      }
      if (this._locked) return intents;

      this._emitMotion(states, intents, timestampMs);

      for (const st of states) {
        if (st.openPalm) {
          this._emitExplode(st, intents, timestampMs);
        } else {
          st.explodeBaselineZ = null;
        }

        if (st.pointing) {
          this._emitPointDwell(st, intents, timestampMs);
        } else {
          st.dwellAnchor = null;
          st.dwellStart = null;
          st.selectFired = false;
        }
      }

      return intents;
    }

    _observeHand(st, landmarks, ts) {
      const wrist = landmarks[WRIST];
      const curled = FINGERS.map((f) => isFingerCurled(landmarks, f, wrist, this.cfg.curlRatio));
      st.fist = curled.every(Boolean);
      st.openPalm = curled.every((c) => !c);
      st.pointing = !curled[0] && curled[1] && curled[2] && curled[3];

      const pinchDist = dist(landmarks[THUMB_TIP], landmarks[INDEX_TIP]);
      if (st.pinching) {
        if (pinchDist > this.cfg.pinchOpenDist) st.pinching = false;
      } else if (pinchDist < this.cfg.pinchCloseDist) {
        st.pinching = true;
      }

      st.prevPinchCenter = st.pinchCenter;
      const rawPinchCenter = mid(landmarks[THUMB_TIP], landmarks[INDEX_TIP]);
      st.pinchCenter = st.filtPinchCenter.update(rawPinchCenter, ts);

      st.pointFiltered = st.filtPoint.update(landmarks[INDEX_TIP], ts);
      st.palmZ = wrist.z || 0;

      return st;
    }

    _emitMotion(states, intents, ts) {
      const pinchingHands = states.filter((s) => s.pinching);
      if (states.length === 2 && states[0].pinching && states[1].pinching) {
        const d = dist(states[0].pinchCenter, states[1].pinchCenter);
        if (this._twoHandPrevDist != null) {
          const delta = d - this._twoHandPrevDist;
          if (Math.abs(delta) >= this.cfg.deadZone) {
            this._notify({ type: "zoom", delta, ts }, intents);
          }
        }
        this._twoHandPrevDist = d;
        return;
      }
      this._twoHandPrevDist = null;

      for (const st of pinchingHands) {
        if (!st.prevPinchCenter) continue;
        const dx = st.pinchCenter.x - st.prevPinchCenter.x;
        const dy = st.pinchCenter.y - st.prevPinchCenter.y;
        if (Math.hypot(dx, dy) >= this.cfg.deadZone) {
          this._notify({ type: "rotate", dx, dy, ts }, intents);
        }
      }
    }

    _emitExplode(st, intents, ts) {
      if (st.explodeBaselineZ == null) {
        st.explodeBaselineZ = st.palmZ;
        return;
      }
      const delta = st.palmZ - st.explodeBaselineZ;
      if (delta <= this.cfg.explodeZDelta && ts - this._lastExplodeTs >= this.cfg.explodeCooldownMs) {
        this._lastExplodeTs = ts;
        st.explodeBaselineZ = st.palmZ;
        this._notify({ type: "explode", toggle: true, ts }, intents);
      }
    }

    _emitPointDwell(st, intents, ts) {
      const pos = st.pointFiltered;
      this._notify({ type: "hover", x: pos.x, y: pos.y, ts }, intents);

      if (!st.dwellAnchor) {
        st.dwellAnchor = pos;
        st.dwellStart = ts;
        st.selectFired = false;
        return;
      }
      const moved = Math.hypot(pos.x - st.dwellAnchor.x, pos.y - st.dwellAnchor.y);
      if (moved > this.cfg.selectStabilityRadius) {
        st.dwellAnchor = pos;
        st.dwellStart = ts;
        st.selectFired = false;
        return;
      }
      if (!st.selectFired && ts - st.dwellStart >= this.cfg.selectDwellMs) {
        st.selectFired = true;
        this._notify({ type: "select", x: pos.x, y: pos.y, ts }, intents);
      }
    }
  }

  return { GestureEngine, DEFAULT_CONFIG, dist, isFingerCurled };
});
