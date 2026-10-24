// JARVIS (PySide6 / QtWebEngine) ile sayfa arasindaki kopru.
//  Qt -> sayfa : page.runJavaScript("window.jarvis.setStats({cpu, ram, disk})")
//  sayfa -> Qt : document.title = "jarvis:<olay>:<sayac>"  (ui/hud/boot3d.py titleChanged dinler)
// Tarayicida tek basina acilinca olcumler benzetilir.
import { hud, type Stats } from './store'

const params = new URLSearchParams(window.location.search)

export const options = {
  mode: params.get('mode') === 'idle' ? ('idle' as const) : ('boot' as const),
  // Acilis bittikten sonra kac saniye bekleyip kendiliginden kapansin (0 = kullanici kapatana kadar kal)
  hold: Math.max(0, Number(params.get('hold') ?? 0) || 0),
  embedded: params.get('embedded') === '1',
}

let counter = 0
export function notify(event: 'ready' | 'idle' | 'done' | 'error'): void {
  counter += 1
  document.title = `jarvis:${event}:${counter}`
}

const clamp = (v: unknown) => Math.min(100, Math.max(0, Number(v) || 0))

let lastLive = 0

declare global {
  interface Window {
    jarvis: { setStats: (s: Partial<Stats>) => void; dismiss: () => void }
  }
}

export function installBridge(onDismiss: () => void): () => void {
  window.jarvis = {
    setStats(s) {
      lastLive = performance.now()
      hud.stats({ cpu: clamp(s.cpu), ram: clamp(s.ram), disk: clamp(s.disk) }, true)
    },
    dismiss: onDismiss,
  }

  // JARVIS'ten olcum gelmiyorsa (tarayicida gelistirme) inandirici bir benzetim
  let cpu = 22
  let ram = 58
  const timer = window.setInterval(() => {
    if (performance.now() - lastLive < 3500 && lastLive > 0) return
    cpu = Math.min(96, Math.max(4, cpu + (Math.random() - 0.5) * 16))
    ram = Math.min(92, Math.max(35, ram + (Math.random() - 0.5) * 3))
    hud.stats({ cpu, ram, disk: 78 }, false)
  }, 1000)
  return () => window.clearInterval(timer)
}
