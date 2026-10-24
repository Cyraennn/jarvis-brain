// 3B Izmir haritasi (CYRAEN icerik paneli, ui/widgets/panel_web.py::open_map).
//  Qt -> sayfa : window.cyraen.show({lat, lon, zoom, label, route?})  yer: kamera suzulur; rota: cizilir
//                window.cyraen.command('zoom_in' | 'zoom_out' | 'rotate' | 'reset')
//                window.cyraen.flyTo(...)  (show'un eski adi)
//  sayfa -> Qt : document.title = "cyraen:<ready|error>:<sayac>"
//  tarayicida gelistirme: ?view=map&lat=..&lon=..&zoom=..&label=.. ilk konumu verir.
// Bostayken kamera yavasca doner; fareyle dokunulunca durur, 10 sn sonra devam eder.
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import './map.css'
import { ACCENT, mapStyle, ROAD_LAYERS, roadOpacity } from './style'

type Point = { lat: number; lon: number; label: string }
type Route = {
  coords: [number, number][]
  origin: Point
  destination: Point
  distance?: string
  duration?: string
  mode?: string
}
type Target = Point & { zoom: number; route?: Route }

const IZMIR: Target = { lat: 38.4237, lon: 27.1428, zoom: 12, label: 'İzmir' }
const PITCH = 60
const ROUTE_PITCH = 50
const ORBIT_DEG_PER_SEC = 2.4
const ORBIT_RESUME_MS = 10_000
const ROUTE_DRAW_MS = 1800
const ZOOM_STEP = 1.2
const ROUTE_CORE = '#ffd2ad' // turuncu yollardan ayrissin: acik, sicak beyaz
const ROAD_DIM = 0.35        // rota acikken diger yollarin parlaklik carpani
const EMPTY_LINE: maplibregl.GeoJSONSourceSpecification['data'] = { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [] } }

let counter = 0
function notify(event: 'ready' | 'error'): void {
  counter += 1
  document.title = `cyraen:${event}:${counter}`
}

function num(v: unknown, fallback: number): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

function parsePoint(src: Record<string, unknown> | undefined, fallback: Point): Point {
  return { lat: num(src?.lat, fallback.lat), lon: num(src?.lon, fallback.lon), label: String(src?.label ?? fallback.label) }
}

function parseRoute(src: unknown): Route | undefined {
  if (!src || typeof src !== 'object') return undefined
  const r = src as Record<string, unknown>
  const coords = (Array.isArray(r.coords) ? r.coords : [])
    .map((c) => (Array.isArray(c) ? [num(c[0], NaN), num(c[1], NaN)] : [NaN, NaN]) as [number, number])
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y))
  if (coords.length < 2) return undefined
  const first = { lat: coords[0][1], lon: coords[0][0], label: '' }
  const last = { lat: coords.at(-1)![1], lon: coords.at(-1)![0], label: '' }
  return {
    coords,
    origin: parsePoint(r.origin as Record<string, unknown>, first),
    destination: parsePoint(r.destination as Record<string, unknown>, last),
    distance: r.distance ? String(r.distance) : undefined,
    duration: r.duration ? String(r.duration) : undefined,
    mode: r.mode ? String(r.mode) : undefined,
  }
}

function parseTarget(src: Record<string, unknown>): Target {
  return {
    ...parsePoint(src, IZMIR),
    zoom: Math.min(19, Math.max(9, num(src.zoom, IZMIR.zoom))),
    route: parseRoute(src.route),
  }
}

function markerElement(variant: 'target' | 'origin'): HTMLDivElement {
  // sabit sablon; yer adi asagida textContent ile yazilir
  const el = document.createElement('div')
  el.className = `map-marker map-marker-${variant}`
  el.innerHTML = '<span class="map-marker-ring"></span><span class="map-marker-dot"></span><span class="map-marker-label"></span>'
  return el
}

/** Cizginin 0..p kismi turuncu, kalani gorunmez (rota ciziliyor efekti). */
function drawGradient(p: number): maplibregl.ExpressionSpecification {
  if (p >= 0.999) return ['interpolate', ['linear'], ['line-progress'], 0, ROUTE_CORE, 1, ROUTE_CORE]
  const edge = Math.max(0.0001, p)
  return ['interpolate', ['linear'], ['line-progress'], 0, ROUTE_CORE, edge, ROUTE_CORE, Math.min(1, edge + 0.0001), 'rgba(0,0,0,0)']
}

export default function MapApp() {
  const box = useRef<HTMLDivElement>(null)
  const [hud, setHud] = useState('')
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const params = Object.fromEntries(new URLSearchParams(window.location.search))
    const fromUrl = params.lat ? parseTarget(params) : null
    let map: maplibregl.Map
    try {
      const start = fromUrl ?? IZMIR
      map = new maplibregl.Map({
        container: box.current!,
        style: mapStyle,
        center: [start.lon, start.lat],
        zoom: Math.max(9, start.zoom - 3), // uzaktan baslar, hedefe suzulur
        pitch: 30,
        bearing: -20,
        maxPitch: 75,
        attributionControl: { compact: true },
        canvasContextAttributes: { antialias: true },
      })
    } catch {
      setFailed(true)
      notify('error')
      return
    }

    const targetEl = markerElement('target')
    const originEl = markerElement('origin')
    const target = new maplibregl.Marker({ element: targetEl })
    const origin = new maplibregl.Marker({ element: originEl })
    const setText = (el: HTMLElement, text: string) => {
      el.querySelector('.map-marker-label')!.textContent = text
    }

    // yorunge donusu (setBearing) suren kamera hareketini keser: hareket bitene kadar beklenir
    let flying = false
    const moving = () => {
      flying = true
      map.once('moveend', () => { flying = false })
    }

    let drawRaf = 0
    const routeSource = () => map.getSource('route') as maplibregl.GeoJSONSource | undefined

    const dimRoads = (on: boolean) => {
      for (const id of Object.keys(ROAD_LAYERS)) map.setPaintProperty(id, 'line-opacity', roadOpacity(id, on ? ROAD_DIM : 1))
    }

    const clearRoute = () => {
      cancelAnimationFrame(drawRaf)
      routeSource()?.setData(EMPTY_LINE)
      origin.remove()
      dimRoads(false)
    }

    const showPoint = (t: Target) => {
      clearRoute()
      setHud(t.label)
      setText(targetEl, t.label)
      target.setLngLat([t.lon, t.lat]).addTo(map)
      moving()
      map.flyTo({ center: [t.lon, t.lat], zoom: t.zoom, pitch: PITCH, bearing: map.getBearing() + 35,
        duration: 3200, curve: 1.6, essential: true })
    }

    const showRoute = (r: Route) => {
      clearRoute()
      setHud([`${r.origin.label} → ${r.destination.label}`, r.distance, r.duration].filter(Boolean).join(' · '))
      setText(originEl, r.origin.label)
      setText(targetEl, r.destination.label)
      origin.setLngLat([r.origin.lon, r.origin.lat]).addTo(map)
      target.setLngLat([r.destination.lon, r.destination.lat]).addTo(map)
      routeSource()?.setData({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: r.coords } })
      dimRoads(true)

      // kamera tum rotayi kapsar; cizgi bastan sona "cizilir"
      const bounds = r.coords.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(r.coords[0], r.coords[0]))
      moving()
      map.fitBounds(bounds, { padding: { top: 90, bottom: 90, left: 80, right: 80 }, pitch: ROUTE_PITCH,
        bearing: map.getBearing(), duration: 2600, maxZoom: 16.5, essential: true })
      const t0 = performance.now()
      const step = (now: number) => {
        const p = Math.min(1, Math.max(0, (now - t0) / ROUTE_DRAW_MS))   // ilk kare t0'dan once gelebilir
        map.setPaintProperty('route-line', 'line-gradient', drawGradient(p))
        map.setPaintProperty('route-glow', 'line-opacity', 0.55 * p)
        if (p < 1) drawRaf = requestAnimationFrame(step)
      }
      drawRaf = requestAnimationFrame(step)
    }

    const show = (t: Target) => (t.route ? showRoute(t.route) : showPoint(t))

    const command = (action: string) => {
      pause()
      moving()
      if (action === 'zoom_in') map.easeTo({ zoom: Math.min(19, map.getZoom() + ZOOM_STEP), duration: 900 })
      else if (action === 'zoom_out') map.easeTo({ zoom: Math.max(9, map.getZoom() - ZOOM_STEP), duration: 900 })
      else if (action === 'rotate') map.easeTo({ bearing: map.getBearing() + 90, duration: 1400 })
      else if (action === 'reset') showPoint(IZMIR)
      else flying = false
    }

    // bostayken yavas yorunge
    let orbit = true
    let resumeTimer = 0
    let last = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const dt = (now - last) / 1000
      last = now
      if (orbit && !flying && !map.isMoving()) map.setBearing(map.getBearing() + ORBIT_DEG_PER_SEC * dt)
      raf = requestAnimationFrame(tick)
    }
    function pause() {
      orbit = false
      window.clearTimeout(resumeTimer)
      resumeTimer = window.setTimeout(() => { orbit = true }, ORBIT_RESUME_MS)
    }
    const canvas = map.getCanvasContainer()
    for (const ev of ['mousedown', 'wheel', 'touchstart'] as const) canvas.addEventListener(ev, pause, { passive: true })

    const bridge = {
      show: (t: Record<string, unknown>) => show(parseTarget(t ?? {})),
      flyTo: (t: Record<string, unknown>) => show(parseTarget(t ?? {})),
      command: (a: unknown) => command(String(a)),
    }
    ;(window as unknown as { cyraen: typeof bridge }).cyraen = bridge

    map.once('load', () => {
      // rota katmanlari binalarin ve etiketlerin altinda degil, ustunde: once parlama, sonra cizgi
      map.addSource('route', { type: 'geojson', data: EMPTY_LINE, lineMetrics: true })
      map.addLayer({
        id: 'route-glow', type: 'line', source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ACCENT, 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 12, 17, 24], 'line-blur': 9, 'line-opacity': 0 },
      })
      map.addLayer({
        id: 'route-line', type: 'line', source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 3.5, 17, 7], 'line-gradient': drawGradient(0) },
      })
      if (fromUrl) show(fromUrl)
      else {
        moving()
        map.flyTo({ center: [IZMIR.lon, IZMIR.lat], zoom: IZMIR.zoom, pitch: PITCH, duration: 2600, essential: true })
      }
      raf = requestAnimationFrame(tick)
      notify('ready')
    })

    return () => {
      cancelAnimationFrame(raf)
      cancelAnimationFrame(drawRaf)
      window.clearTimeout(resumeTimer)
      map.remove()
    }
  }, [])

  return (
    <div className="map-page">
      <div ref={box} className="map-canvas" />
      <div className="map-vignette" />
      {hud && <div className="map-hud">⌖ {hud}</div>}
      {failed && <div className="map-error">Bu cihazda 3B harita çizilemiyor (WebGL yok).</div>}
    </div>
  )
}
