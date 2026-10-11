// Plain-node test harness (no jest / no build step) - `node gestures.test.js`.
// Exercises gesture-engine.js purely against fixture landmark arrays, no webcam needed.

"use strict";

const path = require("path");
const { GestureEngine } = require(path.join(__dirname, "..", "gesture-engine.js"));
const { DeixisBuffer, resolveCommand, containsDeixis } = require(path.join(__dirname, "..", "deixis.js"));

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`ok - ${name}`);
  } catch (err) {
    failed++;
    console.log(`FAIL - ${name}`);
    console.log(`       ${err.message}`);
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

function assertEqual(actual, expected, msg) {
  if (actual !== expected) {
    throw new Error(`${msg || "not equal"}: expected ${expected}, got ${actual}`);
  }
}

// ---------------------------------------------------------------- fixtures

function blankLandmarks() {
  const lm = new Array(21);
  for (let i = 0; i < 21; i++) lm[i] = { x: 0, y: 0, z: 0 };
  return lm;
}

const FINGER_DEFS = [
  { mcp: 5, pip: 6, tip: 8, dx: 0.1 },
  { mcp: 9, pip: 10, tip: 12, dx: 0.2 },
  { mcp: 13, pip: 14, tip: 16, dx: 0.3 },
  { mcp: 17, pip: 18, tip: 20, dx: 0.4 },
];

function makeHand({ curled = [false, false, false, false], thumb = { x: 0.6, y: 0.9, z: 0 }, wristZ = 0 } = {}) {
  const lm = blankLandmarks();
  lm[0] = { x: 0, y: 0, z: wristZ };
  lm[4] = thumb;
  FINGER_DEFS.forEach((f, i) => {
    lm[f.mcp] = { x: f.dx, y: 0.5, z: 0 };
    lm[f.pip] = { x: f.dx, y: curled[i] ? 0.35 : 0.8, z: 0 };
    lm[f.tip] = { x: f.dx, y: curled[i] ? 0.2 : 1.1, z: 0 };
  });
  return lm;
}

function indexTipOf(hand) {
  return hand[8];
}

function openPalmHand(wristZ = 0) {
  return makeHand({ curled: [false, false, false, false], thumb: { x: -0.3, y: 0.9, z: 0 }, wristZ });
}

function fistHand() {
  return makeHand({ curled: [true, true, true, true], thumb: { x: 0.6, y: 0.9, z: 0 } });
}

function pointingHand() {
  return makeHand({ curled: [false, true, true, true], thumb: { x: 0.6, y: 0.9, z: 0 } });
}

function pinchHand({ offsetX = 0, offsetY = 0 } = {}) {
  const hand = makeHand({ curled: [false, false, false, false] });
  const tip = indexTipOf(hand);
  hand[4] = { x: tip.x + 0.02 + offsetX, y: tip.y - 0.02 + offsetY, z: 0 };
  hand[8] = { x: tip.x + offsetX, y: tip.y + offsetY, z: 0 };
  return hand;
}

// ---------------------------------------------------------------- tests

test("open palm alone produces no intents", () => {
  const engine = new GestureEngine();
  const intents = engine.processFrame([openPalmHand()], 0);
  assertEqual(intents.length, 0, "open palm baseline frame should be silent (sets explode baseline)");
});

test("fist edge-triggers a single lock intent", () => {
  const engine = new GestureEngine();
  engine.processFrame([openPalmHand()], 0);
  const first = engine.processFrame([fistHand()], 33);
  assertEqual(first.filter((i) => i.type === "lock").length, 1, "expected exactly one lock intent");
  assert(first[0].locked === true, "lock intent should report locked=true");

  const second = engine.processFrame([fistHand()], 66);
  assertEqual(second.filter((i) => i.type === "lock").length, 0, "holding fist must not re-fire lock");
});

test("locking suppresses other intents until unlocked", () => {
  const engine = new GestureEngine();
  engine.processFrame([openPalmHand()], 0);
  engine.processFrame([fistHand()], 33);
  assert(engine.isLocked(), "engine should report locked");

  const whilePointing = engine.processFrame([pointingHand()], 66);
  assertEqual(whilePointing.length, 0, "pointing while locked should produce nothing");

  const unlock = engine.processFrame([fistHand()], 99);
  assertEqual(unlock.filter((i) => i.type === "lock").length, 1, "second fist should toggle unlock");
  assert(!engine.isLocked(), "engine should report unlocked");
});

test("pinch + drag emits rotate with the correct sign", () => {
  const engine = new GestureEngine();
  engine.processFrame([pinchHand()], 0);
  const moved = engine.processFrame([pinchHand({ offsetX: 0.05, offsetY: 0.03 })], 33);
  const rotate = moved.find((i) => i.type === "rotate");
  assert(rotate, "expected a rotate intent after moving a closed pinch");
  assert(rotate.dx > 0, "dx should be positive for a rightward drag");
  assert(rotate.dy > 0, "dy should be positive for a downward drag");
});

test("tiny pinch movement under the dead zone is swallowed", () => {
  const engine = new GestureEngine();
  engine.processFrame([pinchHand()], 0);
  const moved = engine.processFrame([pinchHand({ offsetX: 0.0005, offsetY: 0 })], 33);
  assertEqual(moved.filter((i) => i.type === "rotate").length, 0, "sub-dead-zone drag must not rotate");
});

test("two-hand pinch spread emits zoom", () => {
  const engine = new GestureEngine();
  const near = [pinchHand({ offsetX: -0.3 }), pinchHand({ offsetX: 0.3 })];
  engine.processFrame(near, 0);
  const far = [pinchHand({ offsetX: -0.6 }), pinchHand({ offsetX: 0.6 })];
  const intents = engine.processFrame(far, 33);
  const zoom = intents.find((i) => i.type === "zoom");
  assert(zoom, "expected a zoom intent when both pinches spread apart");
  assert(zoom.delta > 0, "spreading hands apart should give a positive zoom delta");
});

test("open palm forward push toggles explode once, then cools down", () => {
  const engine = new GestureEngine();
  engine.processFrame([openPalmHand(0)], 0);
  const pushed = engine.processFrame([openPalmHand(-0.1)], 33);
  assertEqual(pushed.filter((i) => i.type === "explode").length, 1, "forward push should toggle explode");

  const pushedAgain = engine.processFrame([openPalmHand(-0.2)], 66);
  assertEqual(pushedAgain.filter((i) => i.type === "explode").length, 0, "explode cooldown should block re-trigger");
});

test("hover fires every frame while pointing, select fires once after the dwell", () => {
  const engine = new GestureEngine({ selectDwellMs: 400 });
  const hand = pointingHand();
  let allIntents = [];
  const frameGapMs = 33;
  let ts = 0;
  for (let i = 0; i < 16; i++) {
    allIntents = allIntents.concat(engine.processFrame([hand], ts));
    ts += frameGapMs;
  }
  const hovers = allIntents.filter((i) => i.type === "hover");
  const selects = allIntents.filter((i) => i.type === "select");
  assert(hovers.length >= 10, `expected many hover intents, got ${hovers.length}`);
  assertEqual(selects.length, 1, `expected exactly one select intent, got ${selects.length}`);
});

test("losing the hand resets dwell state (no stale select on return)", () => {
  const engine = new GestureEngine({ selectDwellMs: 400 });
  const hand = pointingHand();
  let ts = 0;
  for (let i = 0; i < 8; i++) {
    engine.processFrame([hand], ts);
    ts += 33;
  }
  engine.processFrame([], ts); // hand disappears
  ts += 33;
  const resumed = engine.processFrame([hand], ts);
  assertEqual(resumed.filter((i) => i.type === "select").length, 0, "select should not fire immediately after hand returns");
});

// ---------------------------------------------------------------- deixis

test("deixis buffer resolves the most recent hovered part inside the window", () => {
  const buf = new DeixisBuffer(800);
  buf.push("alternator", 0);
  buf.push("belt", 500);
  assertEqual(buf.resolve(600), "belt", "should resolve to the latest hover");
});

test("deixis buffer forgets parts outside the window", () => {
  const buf = new DeixisBuffer(800);
  buf.push("alternator", 0);
  assertEqual(buf.resolve(2000), null, "stale hover should not resolve");
});

test("resolveCommand substitutes a deictic pronoun with the resolved part", () => {
  assert(containsDeixis("bunu ac"), "should detect the pronoun");
  assertEqual(resolveCommand("bunu ac", "alternator"), "alternator ac");
});

// ---------------------------------------------------------------- summary

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
