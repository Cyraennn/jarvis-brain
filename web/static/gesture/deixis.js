(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) {
    module.exports = factory();
  } else {
    root.CyraenDeixis = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const DEIXIS_WORDS = ["bunu", "şunu", "onu", "bu ", "şu ", "burayı", "şurayı"];

  // Ring buffer of recently-hovered part names, so a voice command like
  // "bunu ac" can resolve "bunu" to whatever the hand was pointing at.
  class DeixisBuffer {
    constructor(windowMs = 800) {
      this.windowMs = windowMs;
      this._entries = [];
    }

    push(part, ts) {
      if (!part) return;
      this._entries.push({ part, ts });
      this._trim(ts);
    }

    _trim(nowTs) {
      const cutoff = nowTs - this.windowMs;
      while (this._entries.length && this._entries[0].ts < cutoff) {
        this._entries.shift();
      }
    }

    resolve(nowTs) {
      this._trim(nowTs != null ? nowTs : Date.now());
      if (!this._entries.length) return null;
      return this._entries[this._entries.length - 1].part;
    }

    clear() {
      this._entries = [];
    }
  }

  function containsDeixis(text) {
    const lower = (text || "").toLowerCase();
    return DEIXIS_WORDS.some((w) => lower.includes(w));
  }

  // Replaces the first deictic pronoun in `text` with `part` so a phrase like
  // "bunu ac" becomes "alternator ac" before it is sent on as a command.
  function resolveCommand(text, part) {
    if (!part) return text;
    const lower = (text || "").toLowerCase();
    for (const word of DEIXIS_WORDS) {
      const idx = lower.indexOf(word);
      if (idx !== -1) {
        return (text.slice(0, idx) + part + " " + text.slice(idx + word.length)).replace(/\s+/g, " ").trim();
      }
    }
    return text;
  }

  return { DeixisBuffer, containsDeixis, resolveCommand, DEIXIS_WORDS };
});
