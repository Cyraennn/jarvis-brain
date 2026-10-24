import { createRoot } from 'react-dom/client'

// ?view=orb -> ana penceredeki Zoey tarzi orb (ui/hud/orb_view.py); aksi halde 3B zirh acilisi.
// Ayri parcalar halinde yuklenir: orb sayfasina zirh kodu ve Tailwind stilleri karismaz.
const root = createRoot(document.getElementById('root')!)
const view = new URLSearchParams(window.location.search).get('view')

if (view === 'orb') {
  import('./orb/OrbApp').then(({ default: OrbApp }) => root.render(<OrbApp />))
} else if (view === 'map') {
  // ?view=map -> icerik panelindeki 3B Izmir haritasi (ui/widgets/panel_web.py::open_map)
  import('./map/MapApp').then(({ default: MapApp }) => root.render(<MapApp />))
} else {
  Promise.all([import('./App'), import('./index.css')]).then(([{ default: App }]) => root.render(<App />))
}
