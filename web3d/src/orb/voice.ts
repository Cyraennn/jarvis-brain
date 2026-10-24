// Orb sayfasinin durumu + JARVIS (QtWebEngine) koprusu.
//  Qt -> sayfa : window.jarvis.setVoice({state, level, thinking, asleep})
//                window.jarvis.setCaption(text) / setStatus(text) / setActive(bool) / intro()
//                window.jarvis.setTheme({persona, accent, base, equator, pole})  (kisilik temasi)
//  sayfa -> Qt : document.title = "jarvis:<ready|landed|mic>:<sayac>"  (ui/hud/orb_view.py dinler)
// Tarayicida tek basina acilinca "konusma" benzetimi alt hapa tiklayinca oynar.
import { useSyncExternalStore } from 'react'

export type VoiceState = 'idle' | 'listening' | 'speaking'

const params = new URLSearchParams(window.location.search)
export const embedded = params.get('embedded') === '1'

/** Sahnenin her karede okudugu degisken nesne (React'siz). */
export const live = {
  amp: 0,             // 0..1, Zoey ile ayni olcek: min(1, rms * 3.2)
  thinking: false,
  asleep: false,
  introAt: performance.now(),
  // kisilik temasi: sahne parcacik renklerini bunlara dogru yumusakca kaydirir
  persona: 'jarvis',
  equator: '#22e3ff',
  pole: '#1e8fff',
}

export type OrbTheme = { persona?: string; accent?: string; base?: string; equator?: string; pole?: string }

/** CSS degiskenleri + `data-persona` (orb.css efektleri) + parcacik hedef renkleri. */
export function applyTheme(t: OrbTheme): void {
  const root = document.documentElement
  if (t.base) root.style.setProperty('--o', t.base)
  if (t.accent) {
    root.style.setProperty('--accent', t.accent)
    root.style.setProperty('--hc-accent', t.accent)
  }
  if (t.persona) {
    live.persona = t.persona
    root.dataset.persona = t.persona
  }
  if (t.equator) live.equator = t.equator
  if (t.pole) live.pole = t.pole
}

type View = {
  state: VoiceState
  caption: string
  status: string
  active: boolean
  landed: boolean
}

let view: View = { state: 'idle', caption: '', status: 'HAZIR', active: true, landed: false }
const listeners = new Set<() => void>()

export const orb = {
  get: () => view,
  set(patch: Partial<View>) {
    view = { ...view, ...patch }
    listeners.forEach((fn) => fn())
  },
  subscribe(fn: () => void) {
    listeners.add(fn)
    return () => listeners.delete(fn)
  },
}

export function useOrb<T>(pick: (v: View) => T): T {
  return useSyncExternalStore(orb.subscribe, () => pick(view))
}

let counter = 0
export function notify(event: 'ready' | 'landed' | 'mic' | 'error'): void {
  counter += 1
  document.title = `jarvis:${event}:${counter}`
}

type VoicePatch = { state?: VoiceState; level?: number; thinking?: boolean; asleep?: boolean }

type OrbBridge = {
  setVoice: (v: VoicePatch) => void
  setCaption: (text: string) => void
  setStatus: (text: string) => void
  setActive: (active: boolean) => void
  intro: () => void
  setTheme: (t: OrbTheme) => void
}

export function installOrbBridge(): () => void {
  // zirh sayfasinin `window.jarvis` tipi baska; iki sayfa ayni anda yuklenmez
  const bridge: OrbBridge = {
    setVoice(v) {
      if (typeof v.level === 'number') live.amp = Math.min(1, Math.max(0, v.level) * 3.2)
      if (typeof v.thinking === 'boolean') live.thinking = v.thinking
      if (typeof v.asleep === 'boolean') live.asleep = v.asleep
      if (v.state && v.state !== view.state) orb.set({ state: v.state })
    },
    setCaption: (text) => orb.set({ caption: String(text ?? '') }),
    setStatus: (text) => orb.set({ status: String(text ?? '') }),
    setActive: (active) => orb.set({ active: Boolean(active) }),
    intro() {
      live.introAt = performance.now()
      orb.set({ landed: false })
    },
    setTheme: (t) => applyTheme(t ?? {}),
  }
  ;(window as unknown as { jarvis: OrbBridge }).jarvis = bridge
  return () => undefined
}

/** Tarayicida gelistirirken: alt hap konusma benzetimi oynatir. */
let demoTimer = 0
export function demoSpeak(): void {
  if (embedded || demoTimer) return
  const text = 'Emrinizdeyim efendim. Bugün takviminizde iki toplantı ve bir ödev teslimi var.'
  orb.set({ state: 'speaking', caption: text })
  const t0 = performance.now()
  demoTimer = window.setInterval(() => {
    const t = (performance.now() - t0) / 1000
    live.amp = Math.max(0, 0.35 + 0.3 * Math.sin(t * 9) * Math.sin(t * 2.3) + (Math.random() - 0.5) * 0.25)
    if (t > 4.5) {
      window.clearInterval(demoTimer)
      demoTimer = 0
      live.amp = 0
      orb.set({ state: 'idle' })
    }
  }, 40)
}
