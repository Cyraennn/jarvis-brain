// JARVIS HUD katmani (HTML + Tailwind): sade, cercevesiz; 3B sahnenin ustunde durur ve fareyi
// sahneye gecirir. Parca etiketleri sahnenin icindedir (scene/Armor.tsx, Callout).
import { useEffect, useState } from 'react'
import { useHud, type Stage } from '../store'

const STAGE_STYLE: Record<Stage['state'], { mark: string; text: string }> = {
  bekliyor: { mark: 'bg-ink/15', text: 'text-ink/30' },
  kuruluyor: { mark: 'bg-gold hud-blink', text: 'text-gold' },
  hazir: { mark: 'bg-mint', text: 'text-ink/80' },
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span className={value >= 90 ? 'text-gold' : ''}>
      <span className="text-arc-dim">{label} </span>
      <span className="tabular-nums">%{Math.round(value)}</span>
    </span>
  )
}

export default function Hud({ onDismiss, countdown }: { onDismiss: () => void; countdown: number | null }) {
  const phase = useHud((s) => s.phase)
  const power = useHud((s) => s.power)
  const log = useHud((s) => s.log)
  const stages = useHud((s) => s.stages)
  const stats = useHud((s) => s.stats)

  const started = phase !== 'dark'
  const online = phase === 'idle' || phase === 'leaving'

  // Karsilama yazisi birkac saniye gorunur, sonra zirhin onunden cekilir
  const [greet, setGreet] = useState(false)
  useEffect(() => {
    if (phase !== 'idle') return
    setGreet(true)
    const timer = window.setTimeout(() => setGreet(false), 3200)
    return () => window.clearTimeout(timer)
  }, [phase])

  return (
    <div className={`pointer-events-none absolute inset-0 overflow-hidden transition-opacity duration-700 ${started ? 'opacity-100' : 'opacity-0'}`}>
      {/* sol ust: ad + durum */}
      <header className="absolute left-8 top-7">
        <h1 className="text-lg font-semibold tracking-[0.5em] text-ink">J.A.R.V.I.S</h1>
        <p className={`mt-1 flex items-center gap-2 font-mono text-[0.66rem] tracking-[0.22em] ${online ? 'text-mint' : 'text-gold'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${online ? 'bg-mint' : 'bg-gold hud-blink'}`} />
          {online ? 'ÇEVRİMİÇİ' : `BAŞLATILIYOR · %${power}`}
        </p>
      </header>

      {/* sag: asamalar */}
      <ul className="absolute right-8 top-8 space-y-2">
        {stages.map((s) => {
          const style = STAGE_STYLE[s.state]
          return (
            <li key={s.key} className={`flex items-center justify-end gap-2.5 font-mono text-[0.66rem] tracking-[0.18em] transition-colors duration-500 ${style.text}`}>
              {s.label}
              <span className={`h-0.5 w-5 ${style.mark}`} />
            </li>
          )
        })}
      </ul>

      {/* karsilama */}
      <p className={`absolute inset-x-0 bottom-9 text-center text-sm tracking-[0.42em] text-ink transition-all duration-700 ${greet ? 'translate-y-0 opacity-100' : 'translate-y-1 opacity-0'}`}>
        “Emrinizdeyim efendim.”
      </p>

      {/* alt serit: gunluk + olcumler + cikis */}
      <footer className="absolute inset-x-8 bottom-7 flex items-end justify-between gap-6">
        <div className="min-w-0 font-mono text-[0.66rem] tracking-[0.14em]">
          <p className="truncate text-ink/70">
            <span className="text-arc-dim">&gt; </span>
            {online ? 'Sürükle: döndür · Tekerlek: yakınlaştır · Esc: arayüze geç' : (log[log.length - 1] ?? '')}
          </p>
          <p className="mt-1.5 flex gap-5 text-ink/70">
            <Stat label="CPU" value={stats.cpu} />
            <Stat label="RAM" value={stats.ram} />
            <Stat label="DİSK" value={stats.disk} />
          </p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="pointer-events-auto shrink-0 border border-arc/40 px-4 py-1.5 font-mono text-[0.7rem] tracking-[0.22em] text-arc transition-colors hover:border-arc hover:bg-arc/10 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-arc"
        >
          {online ? 'ARAYÜZE GEÇ' : 'ATLA'}
          {countdown !== null && <span className="ml-2 tabular-nums text-arc-dim">{countdown}</span>}
        </button>
      </footer>

      {/* cikis perdesi */}
      <div className={`absolute inset-0 bg-hud transition-opacity duration-500 ${phase === 'leaving' ? 'opacity-100' : 'opacity-0'}`} />
    </div>
  )
}
