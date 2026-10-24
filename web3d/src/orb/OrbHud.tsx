// Orb'un altindaki Zoey tarzi arayuz: konusma balonu, dalga hapi ve mono durum satiri;
// arkada kose isimalari ve yavas akan yetenek seridi.
import { useEffect, useRef } from 'react'
import { demoSpeak, embedded, live, notify, useOrb } from './voice'

// zoeyos.com dalga cubuklari (yukseklik px); "xtra" olanlar yalnizca konusurken gorunur
const BARS: { h: number; xtra: boolean }[] = [
  [7, 1], [9, 0], [14, 1], [17, 0], [22, 1], [26, 0], [15, 0], [19, 1], [10, 0],
  [16, 1], [20, 0], [24, 1], [13, 0], [18, 1], [24, 0], [14, 1], [11, 0], [8, 1],
].map(([h, x]) => ({ h, xtra: Boolean(x) }))

const ABILITIES = [
  'Planla', 'Hatırla', 'Araştır', 'Yaz', 'Düzenle', 'Takip et', 'Otomatikleştir',
  'Bağlan', 'Öğren', 'Koru', 'Sadeleştir', 'Yönet',
]

function Wave({ driven }: { driven: boolean }) {
  const bars = useRef<(HTMLSpanElement | null)[]>([])
  useEffect(() => {
    if (!driven) {
      bars.current.forEach((el) => el && (el.style.transform = ''))
      return
    }
    let raf = 0
    const tick = () => {
      const amp = live.amp
      bars.current.forEach((el, i) => {
        if (el) el.style.transform = `scaleY(${0.25 + amp * (0.85 + 0.4 * Math.sin(i * 2.1))})`
      })
      raf = requestAnimationFrame(tick)
    }
    tick()
    return () => cancelAnimationFrame(raf)
  }, [driven])

  return (
    <span className="hc-wave" aria-hidden="true">
      {BARS.map((b, i) => (
        <span
          key={i}
          ref={(el) => {
            bars.current[i] = el
          }}
          className={b.xtra ? 'xtra' : undefined}
          style={{ '--h': `${b.h}px`, '--i': i } as React.CSSProperties}
        />
      ))}
    </span>
  )
}

export default function OrbHud() {
  const state = useOrb((v) => v.state)
  const caption = useOrb((v) => v.caption)
  const status = useOrb((v) => v.status)
  const landed = useOrb((v) => v.landed)
  // dinlerken mikrofon, konusurken hoparlor genligi cubuklari surer
  const driven = state === 'speaking' || state === 'listening'

  const onPill = () => {
    if (embedded) notify('mic')
    else demoSpeak()
  }

  return (
    <>
      <div className="corner-glow corner-glow-tl" />
      <div className="corner-glow corner-glow-tr" />

      <div className="ticker-wrap" aria-hidden="true">
        <div className="ticker-track">
          {[...ABILITIES, ...ABILITIES].map((w, i) => (
            <span key={i}>{w}</span>
          ))}
        </div>
      </div>

      <section className="hc-root" data-state={state} data-driven={driven} data-landed={landed}>
        <p className="hc-bubble" aria-live="polite">
          {caption}
        </p>
        <div className="hc-hud">
          <button
            type="button"
            className="hc-voice"
            onClick={onPill}
            title={embedded ? 'Mikrofonu aç / kapat' : 'Konuşma benzetimi'}
          >
            <Wave driven={driven} />
            <span className="hc-say-hi">“Merhaba Siren” de</span>
          </button>
          <p className="hc-status">{status}</p>
        </div>
      </section>
    </>
  )
}
