// Iki katmanli durum:
//  - `anim`: GSAP'in dogrudan tween'ledigi, sahnenin her karede okudugu degisken nesne (React'siz).
//  - `hud`:  HTML arayuzunun abone oldugu kucuk depo (faz, gunluk, asamalar, sistem olcumleri).
import { useSyncExternalStore } from 'react'

export const GROUPS = [
  'torso', 'pelvis', 'thighs', 'shins', 'boots',
  'shoulders', 'arms', 'forearms', 'gloves', 'neck', 'helmet',
] as const
export type Group = (typeof GROUPS)[number]

const zeroGroups = () => Object.fromEntries(GROUPS.map((g) => [g, 0])) as Record<Group, number>

export const anim = {
  solid: zeroGroups(),    // 0..1: parcanin hologram kabugu ne kadar olustu
  holo: zeroGroups(),     // 0..1: kenar cizgileri ne kadar yayildi (kabuktan once gelir)
  reactor: 0,             // Arc Reactor parlakligi
  eyes: 0,
  repulsors: 0,
  spin: 0,                // acilistaki 360 derece donus (radyan)
  dolly: 0,               // 0..1 kamera yaklasmasi
  grid: 0,                // zemin izgarasi + hologram yayicisi
  scan: 0,                // lazer tarama halkasi gorunurlugu
  scanY: 1.4,
  arcs: 0,                // reactor ateslenirken kisa enerji arklari
  particles: 0,           // 0..1 parcacik zaman cizgisi
  glb: 0,                 // harici model icin tek parca olusma degeri
}

export type Phase = 'dark' | 'boot' | 'idle' | 'leaving'
export type Stage = { key: string; label: string; state: 'bekliyor' | 'kuruluyor' | 'hazir' }
export type Stats = { cpu: number; ram: number; disk: number }

export const STAGES: Stage[] = [
  { key: 'reactor', label: 'ARC REAKTÖR', state: 'bekliyor' },
  { key: 'torso', label: 'GÖVDE', state: 'bekliyor' },
  { key: 'legs', label: 'BACAKLAR', state: 'bekliyor' },
  { key: 'arms', label: 'KOLLAR', state: 'bekliyor' },
  { key: 'helmet', label: 'KASK', state: 'bekliyor' },
]

const HISTORY = 48

type HudState = {
  phase: Phase
  power: number
  log: string[]
  stages: Stage[]
  stats: Stats
  cpuHistory: number[]
  ramHistory: number[]
  live: boolean           // olcumler gercek mi (JARVIS'ten) yoksa benzetim mi
  model: 'procedural' | 'glb'
}

let state: HudState = {
  phase: 'dark',
  power: 0,
  log: [],
  stages: STAGES.map((s) => ({ ...s })),
  stats: { cpu: 0, ram: 0, disk: 0 },
  cpuHistory: [],
  ramHistory: [],
  live: false,
  model: 'procedural',
}

const listeners = new Set<() => void>()
const emit = () => listeners.forEach((fn) => fn())

export const hud = {
  get: () => state,
  set(patch: Partial<HudState>) {
    state = { ...state, ...patch }
    emit()
  },
  log(line: string) {
    state = { ...state, log: [...state.log, line].slice(-7) }
    emit()
  },
  stage(key: string, value: Stage['state']) {
    state = { ...state, stages: state.stages.map((s) => (s.key === key ? { ...s, state: value } : s)) }
    emit()
  },
  stats(next: Stats, live: boolean) {
    state = {
      ...state,
      stats: next,
      live,
      cpuHistory: [...state.cpuHistory, next.cpu].slice(-HISTORY),
      ramHistory: [...state.ramHistory, next.ram].slice(-HISTORY),
    }
    emit()
  },
  subscribe(fn: () => void) {
    listeners.add(fn)
    return () => listeners.delete(fn)
  },
}

export function useHud<T>(pick: (s: HudState) => T): T {
  return useSyncExternalStore(hud.subscribe, () => pick(state))
}
