// Prosedurel zirh (hologram): govde ve uzuvlar tek parca donel (lathe) kabuklardir, ustlerine
// ince plakalar oturur. Koordinatlar "kok uzayi"ndadir: ayak tabani y = 0, boy ~1.92, zirh +z'ye bakar.
// Her parca bir gruba aittir; gruplar acilista sirayla olusur (bkz. timeline.ts).
import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import type { Group } from '../store'

export type Kind = 'shell' | 'core' | 'eye' | 'repulsor'
type V3 = [number, number, number]
type Shape = { geo: THREE.BufferGeometry; edges: THREE.BufferGeometry | null }

type Spec = Shape & {
  group: Group
  kind?: Kind
  pos: V3
  rot?: V3
  scale?: V3
  mirror?: boolean // true: x ekseninde aynalanmis ikinci kopya da uretilir
}

export type Part = Shape & {
  group: Group
  kind: Kind
  pos: V3
  rot: V3
  scale: V3
  side: -1 | 0 | 1 // 0: orta hat, +-1: sag/sol
}

const HALF_PI = Math.PI / 2
const EDGE_ANGLE = 28

const withEdges = (geo: THREE.BufferGeometry, source: THREE.BufferGeometry = geo): Shape => {
  const edges = new THREE.EdgesGeometry(source, EDGE_ANGLE)
  return { geo, edges: edges.getAttribute('position').count > 0 ? edges : null }
}

// Plaka: yuzey yuvarlatilmis, cizgiler keskin kutudan (koselerde tek, temiz cizgi)
const plate = (w: number, h: number, d: number, r = 0.012) =>
  withEdges(new RoundedBoxGeometry(w, h, d, 3, Math.min(r, w / 2.2, h / 2.2, d / 2.2)), new THREE.BoxGeometry(w, h, d))
const cyl = (rt: number, rb: number, h: number) => withEdges(new THREE.CylinderGeometry(rt, rb, h, 36, 1))
const sph = (r = 1) => withEdges(new THREE.SphereGeometry(r, 36, 24))
const tor = (R: number, r: number) => withEdges(new THREE.TorusGeometry(R, r, 10, 56))
// Acik yay plakasi (yuz plakasi): theta = 0 +z yonudur
const arc = (rt: number, rb: number, h: number, half: number) =>
  withEdges(new THREE.CylinderGeometry(rt, rb, h, 28, 1, true, -half, half * 2))
/** Donel kabuk: [yaricap, y] noktalari asagidan yukari. Profildeki kirilmalar yatay panel cizgisi olur. */
const lathe = (points: [number, number][]) =>
  withEdges(new THREE.LatheGeometry(points.map(([r, y]) => new THREE.Vector2(r, y)), 44))
/** Uzuv: profil [yaricap, t] (t = 0 alt uc, 1 ust uc), kendi merkezine gore `len` boyunda. */
const limb = (len: number, profile: [number, number][]) => lathe(profile.map(([r, t]) => [r, (t - 0.5) * len]))

// Olusma efektinin her grupta yayildigi nokta (gogusten disari dogru eklem eklem ilerler)
export const GROUP_ORIGIN: Record<Group, { at: V3; reach: number }> = {
  torso: { at: [0, 1.4, 0.13], reach: 0.52 },
  pelvis: { at: [0, 1.05, 0], reach: 0.3 },
  thighs: { at: [0.105, 0.95, 0], reach: 0.5 },
  shins: { at: [0.105, 0.56, 0], reach: 0.5 },
  boots: { at: [0.105, 0.16, 0], reach: 0.34 },
  shoulders: { at: [0.2, 1.48, 0], reach: 0.3 },
  arms: { at: [0.32, 1.42, 0], reach: 0.34 },
  forearms: { at: [0.35, 1.14, 0], reach: 0.36 },
  gloves: { at: [0.37, 0.87, 0], reach: 0.26 },
  neck: { at: [0, 1.56, 0], reach: 0.16 },
  helmet: { at: [0, 1.63, 0], reach: 0.42 },
}

export const REACTOR_POS: V3 = [0, 1.4, 0.156]
export const EYE_POS: V3 = [0.04, 1.787, 0.13]
export const PALM_POS: V3 = [0.372, 0.79, 0.024]
export const HEAD_PIVOT: V3 = [0, 1.62, 0]
export const BODY_PIVOT: V3 = [0, 1.3, 0]

const THIGH = limb(0.42, [[0, 0], [0.06, 0], [0.066, 0.14], [0.07, 0.2], [0.086, 0.55], [0.09, 0.8], [0.078, 0.96], [0, 1]])
const SHIN = limb(0.39, [[0, 0], [0.05, 0], [0.056, 0.18], [0.06, 0.24], [0.076, 0.55], [0.08, 0.75], [0.066, 0.97], [0, 1]])
const UPPER_ARM = limb(0.27, [[0, 0], [0.047, 0], [0.054, 0.3], [0.064, 0.7], [0.058, 0.95], [0, 1]])
const FOREARM = limb(0.28, [[0, 0], [0.044, 0], [0.05, 0.15], [0.058, 0.3], [0.068, 0.62], [0.07, 0.8], [0.056, 0.97], [0, 1]])

const SPECS: Spec[] = [
  // ---------------------------------------------------------------- govde: dar bel, genis gogus
  {
    group: 'torso',
    ...lathe([[0, 1.03], [0.132, 1.03], [0.138, 1.08], [0.128, 1.15], [0.15, 1.22], [0.2, 1.3], [0.238, 1.38], [0.242, 1.44], [0.2, 1.5], [0.12, 1.545], [0.074, 1.56], [0, 1.56]]),
    pos: [0, 0, 0],
    scale: [1, 1, 0.62],
  },
  { group: 'torso', ...plate(0.19, 0.15, 0.04), pos: [0.105, 1.405, 0.128], rot: [-0.1, 0.24, -0.1], mirror: true },
  { group: 'torso', ...plate(0.17, 0.046, 0.026), pos: [0, 1.262, 0.1] },
  { group: 'torso', ...plate(0.155, 0.044, 0.026), pos: [0, 1.205, 0.09] },
  { group: 'torso', ...plate(0.14, 0.042, 0.026), pos: [0, 1.15, 0.082] },
  { group: 'torso', ...plate(0.13, 0.3, 0.04), pos: [0, 1.36, -0.128] },
  { group: 'torso', ...tor(0.086, 0.011), pos: [0, 1.553, 0], rot: [HALF_PI, 0, 0] },
  // Arc Reactor
  { group: 'torso', ...tor(0.05, 0.007), pos: [0, 1.4, 0.152] },
  { group: 'torso', ...tor(0.027, 0.003), pos: [0, 1.4, 0.158] },
  { group: 'torso', kind: 'core', ...cyl(0.04, 0.04, 0.008), pos: REACTOR_POS, rot: [HALF_PI, 0, 0] },

  // ---------------------------------------------------------------- kalca
  { group: 'pelvis', ...lathe([[0, 0.9], [0.1, 0.9], [0.134, 0.96], [0.14, 1.02], [0.132, 1.045], [0, 1.045]]), pos: [0, 0, 0], scale: [1, 1, 0.7] },
  { group: 'pelvis', ...plate(0.055, 0.11, 0.13), pos: [0.152, 0.97, 0], rot: [0, 0, 0.16], mirror: true },
  { group: 'pelvis', ...plate(0.085, 0.1, 0.05), pos: [0, 0.935, 0.075] },

  // ---------------------------------------------------------------- bacaklar
  { group: 'thighs', ...THIGH, pos: [0.105, 0.73, 0], mirror: true },
  { group: 'thighs', ...plate(0.085, 0.22, 0.026), pos: [0.105, 0.745, 0.08], mirror: true },

  { group: 'shins', ...sph(0.056), pos: [0.105, 0.5, 0], mirror: true },
  { group: 'shins', ...plate(0.082, 0.085, 0.045), pos: [0.105, 0.512, 0.06], mirror: true },
  { group: 'shins', ...SHIN, pos: [0.105, 0.285, 0], mirror: true },
  { group: 'shins', ...plate(0.066, 0.23, 0.026), pos: [0.105, 0.3, 0.07], mirror: true },

  { group: 'boots', ...cyl(0.06, 0.066, 0.05), pos: [0.105, 0.105, 0], mirror: true },
  { group: 'boots', ...plate(0.108, 0.086, 0.25, 0.028), pos: [0.105, 0.044, 0.045], mirror: true },
  { group: 'boots', ...plate(0.098, 0.046, 0.08, 0.02), pos: [0.105, 0.03, 0.172], mirror: true },
  { group: 'boots', kind: 'repulsor', ...cyl(0.034, 0.034, 0.008), pos: [0.105, 0.003, 0.03], mirror: true },

  // ---------------------------------------------------------------- kollar
  { group: 'shoulders', ...sph(), pos: [0.295, 1.475, 0], scale: [0.1, 0.082, 0.108], mirror: true },
  { group: 'shoulders', ...tor(0.066, 0.006), pos: [0.325, 1.46, 0], rot: [0, HALF_PI, 0], mirror: true },

  { group: 'arms', ...UPPER_ARM, pos: [0.335, 1.28, 0], rot: [0, 0, 0.08], mirror: true },

  { group: 'forearms', ...sph(0.05), pos: [0.35, 1.135, 0], mirror: true },
  { group: 'forearms', ...FOREARM, pos: [0.362, 0.99, 0], rot: [0, 0, 0.05], mirror: true },
  { group: 'forearms', ...plate(0.058, 0.18, 0.024), pos: [0.366, 1.0, 0.06], rot: [0, 0, 0.05], mirror: true },

  { group: 'gloves', ...cyl(0.042, 0.042, 0.03), pos: [0.37, 0.85, 0], mirror: true },
  { group: 'gloves', ...plate(0.07, 0.1, 0.04, 0.016), pos: [0.372, 0.79, 0], mirror: true },
  { group: 'gloves', ...plate(0.065, 0.06, 0.036, 0.014), pos: [0.374, 0.715, 0.008], rot: [0.25, 0, 0], mirror: true },
  { group: 'gloves', kind: 'repulsor', ...cyl(0.019, 0.019, 0.006), pos: PALM_POS, rot: [HALF_PI, 0, 0], mirror: true },

  // ---------------------------------------------------------------- boyun + kask
  { group: 'neck', ...cyl(0.05, 0.06, 0.08), pos: [0, 1.6, 0] },

  {
    group: 'helmet',
    ...lathe([[0, 1.632], [0.058, 1.632], [0.084, 1.67], [0.1, 1.73], [0.105, 1.79], [0.098, 1.85], [0.075, 1.895], [0.04, 1.92], [0, 1.926]]),
    pos: [0, 0, 0],
    scale: [1, 1, 1.12],
  },
  // yuz plakasi: kaskin onunu saran yay + cene
  { group: 'helmet', ...arc(0.1, 0.078, 0.2, 0.78), pos: [0, 1.755, 0.012], scale: [1, 1, 1.12] },
  { group: 'helmet', ...plate(0.095, 0.04, 0.06), pos: [0, 1.655, 0.062] },
  { group: 'helmet', ...plate(0.046, 0.005, 0.008, 0.002), pos: [0, 1.695, 0.108] },
  { group: 'helmet', kind: 'eye', ...plate(0.038, 0.009, 0.008, 0.003), pos: EYE_POS, rot: [0, 0.36, -0.14], mirror: true },
]

export const PARTS: Part[] = SPECS.flatMap((s) => {
  const rot = s.rot ?? [0, 0, 0]
  const scale = s.scale ?? [1, 1, 1]
  const base: Part = { group: s.group, kind: s.kind ?? 'shell', geo: s.geo, edges: s.edges, pos: s.pos, rot, scale, side: s.mirror ? 1 : 0 }
  if (!s.mirror) return [base]
  // yz duzlemine gore ayna: konumun x'i, donusun y ve z'si isaret degistirir
  const mirrored: Part = { ...base, pos: [-s.pos[0], s.pos[1], s.pos[2]], rot: [rot[0], -rot[1], -rot[2]], side: -1 }
  return [base, mirrored]
})
