import { useCallback, useEffect, useRef, useState } from 'react'
import { installBridge, notify, options } from './bridge'
import Hud from './hud/Hud'
import { GLB_URL } from './scene/GlbArmor'
import Scene from './scene/Scene'
import { hud, useHud } from './store'
import { createBootTimeline, finishInstantly } from './timeline'

const LEAVE_MS = 520

function hasWebGL2(): boolean {
  try {
    return Boolean(document.createElement('canvas').getContext('webgl2'))
  } catch {
    return false
  }
}

/** public/models/armor.glb gercekten var mi? (Vite gelistirme sunucusu olmayan yola index.html dondurur.) */
async function glbExists(): Promise<boolean> {
  try {
    const res = await fetch(GLB_URL, { method: 'HEAD' })
    return res.ok && !(res.headers.get('content-type') ?? '').includes('text/html')
  } catch {
    return false
  }
}

export default function App() {
  const phase = useHud((s) => s.phase)
  const [useGlb, setUseGlb] = useState<boolean | null>(null)
  const [webgl] = useState(hasWebGL2)
  const [countdown, setCountdown] = useState<number | null>(null)
  const timeline = useRef<ReturnType<typeof createBootTimeline> | null>(null)
  const leaving = useRef(false)

  const dismiss = useCallback(() => {
    if (leaving.current) return
    leaving.current = true
    timeline.current?.kill()
    setCountdown(null)
    hud.set({ phase: 'leaving' })
    window.setTimeout(() => notify('done'), LEAVE_MS)
  }, [])

  // kopru + model secimi
  useEffect(() => {
    const stop = installBridge(dismiss)
    if (!webgl) {
      notify('error')
      return stop
    }
    glbExists().then((found) => {
      hud.set({ model: found ? 'glb' : 'procedural' })
      setUseGlb(found)
    })
    return stop
  }, [dismiss, webgl])

  // acilis: sahne hazir olunca baslar
  const start = useCallback(() => {
    notify('ready')
    if (options.mode === 'idle') {
      finishInstantly()
      notify('idle')
      return
    }
    timeline.current = createBootTimeline(() => {
      notify('idle')
      if (options.hold > 0) setCountdown(Math.ceil(options.hold))
    })
  }, [])

  // bosta geri sayim: kullanici zirhla ilgilenirse iptal olur
  useEffect(() => {
    if (countdown === null) return
    if (countdown <= 0) {
      dismiss()
      return
    }
    const timer = window.setTimeout(() => setCountdown((c) => (c === null ? null : c - 1)), 1000)
    return () => window.clearTimeout(timer)
  }, [countdown, dismiss])

  useEffect(() => {
    const cancel = () => setCountdown(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === 'Enter') dismiss()
    }
    window.addEventListener('pointerdown', cancel)
    window.addEventListener('wheel', cancel, { passive: true })
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', cancel)
      window.removeEventListener('wheel', cancel)
      window.removeEventListener('keydown', onKey)
    }
  }, [dismiss])

  if (!webgl) {
    return (
      <main className="flex h-full items-center justify-center bg-void px-8 text-center">
        <p className="font-mono text-sm tracking-widest text-arc-dim">WebGL 2 kullanılamıyor · 3B zırh gösterilemiyor</p>
      </main>
    )
  }

  return (
    <main className={`relative h-full w-full ${phase === 'idle' ? 'cursor-grab active:cursor-grabbing' : ''}`}>
      {useGlb !== null && <Scene phase={phase} useGlb={useGlb} onReady={start} />}
      <Hud onDismiss={dismiss} countdown={countdown} />
    </main>
  )
}
