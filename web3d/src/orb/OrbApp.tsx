import { useEffect } from 'react'
import OrbHud from './OrbHud'
import OrbScene from './OrbScene'
import { installOrbBridge, notify } from './voice'
import './orb.css'

function hasWebGL2(): boolean {
  try {
    return Boolean(document.createElement('canvas').getContext('webgl2'))
  } catch {
    return false
  }
}

const webgl = hasWebGL2()

export default function OrbApp() {
  useEffect(() => {
    const stop = installOrbBridge()
    if (!webgl) notify('error')
    return stop
  }, [])

  return (
    <main className="orb-page">
      {webgl && <OrbScene onReady={() => notify('ready')} />}
      <OrbHud />
    </main>
  )
}
