(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) {
    module.exports = factory();
  } else {
    root.CyraenSmoothing = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function alphaFor(cutoff, dt) {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
  }

  class LowPassFilter {
    constructor(alpha) {
      this.setAlpha(alpha);
      this._y = 0;
      this._s = 0;
      this._initialized = false;
    }

    setAlpha(alpha) {
      if (!(alpha > 0 && alpha <= 1)) throw new RangeError("alpha must be in (0, 1]");
      this.alpha = alpha;
    }

    filter(value) {
      const result = this._initialized ? this.alpha * value + (1 - this.alpha) * this._s : value;
      this._initialized = true;
      this._y = value;
      this._s = result;
      return result;
    }

    lastValue() {
      return this._y;
    }

    reset() {
      this._initialized = false;
    }
  }

  // Casiez et al. One-Euro filter - trades lag for jitter based on speed of change.
  class OneEuroFilter {
    constructor({ minCutoff = 1.0, beta = 0.0, dCutoff = 1.0 } = {}) {
      this.minCutoff = minCutoff;
      this.beta = beta;
      this.dCutoff = dCutoff;
      this._xFilter = new LowPassFilter(alphaFor(minCutoff, 1 / 30));
      this._dxFilter = new LowPassFilter(alphaFor(dCutoff, 1 / 30));
      this._lastTimeMs = null;
    }

    configure({ minCutoff, beta, dCutoff } = {}) {
      if (typeof minCutoff === "number") this.minCutoff = minCutoff;
      if (typeof beta === "number") this.beta = beta;
      if (typeof dCutoff === "number") this.dCutoff = dCutoff;
    }

    filter(value, timestampMs) {
      let dt = 1 / 30;
      if (this._lastTimeMs != null && timestampMs != null) {
        dt = Math.max((timestampMs - this._lastTimeMs) / 1000, 1e-3);
      }
      this._lastTimeMs = timestampMs != null ? timestampMs : this._lastTimeMs;

      const prevX = this._xFilter.lastValue();
      const dx = this._xFilter._initialized ? (value - prevX) / dt : 0;
      this._dxFilter.setAlpha(alphaFor(this.dCutoff, dt));
      const edx = this._dxFilter.filter(dx);

      const cutoff = this.minCutoff + this.beta * Math.abs(edx);
      this._xFilter.setAlpha(alphaFor(cutoff, dt));
      return this._xFilter.filter(value);
    }

    reset() {
      this._xFilter.reset();
      this._dxFilter.reset();
      this._lastTimeMs = null;
    }
  }

  // Filters a {x,y,z} point independently on each axis with its own OneEuroFilter.
  class FilteredPoint {
    constructor(options) {
      this._fx = new OneEuroFilter(options);
      this._fy = new OneEuroFilter(options);
      this._fz = new OneEuroFilter(options);
    }

    configure(options) {
      this._fx.configure(options);
      this._fy.configure(options);
      this._fz.configure(options);
    }

    update(point, timestampMs) {
      return {
        x: this._fx.filter(point.x, timestampMs),
        y: this._fy.filter(point.y, timestampMs),
        z: this._fz.filter(point.z || 0, timestampMs),
      };
    }

    reset() {
      this._fx.reset();
      this._fy.reset();
      this._fz.reset();
    }
  }

  return { OneEuroFilter, FilteredPoint, LowPassFilter };
});
