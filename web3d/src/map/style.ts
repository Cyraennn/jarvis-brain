// Zoey OS dilinde koyu harita stili: saf siyah zemin, ince turuncu yollar, 3B bina bloklari.
// Veri: OpenFreeMap (OpenStreetMap, OpenMapTiles semasi) - anahtarsiz, ucretsiz.
import type maplibregl from 'maplibre-gl'
import type { StyleSpecification } from 'maplibre-gl'

export const ACCENT = '#ff8c42' // ui/theme.py ACCENT
const ACCENT_BASE = '#ff6d00' // ui/theme.py ACCENT_BASE
const LABEL_FONT = ['Noto Sans Regular']

// Yol katmanlarinin saydamligi [zoom, deger, zoom, deger]. Rota cizilince MapApp bunlari `k` ile
// soluklastirir. Zoom ifadesi en dista olmak zorunda oldugundan carpim kademe degerlerine uygulanir.
export const ROAD_LAYERS: Record<string, number[]> = {
  'roads-minor': [12, 0.08, 16, 0.3],
  'roads-major': [9, 0.35, 15, 0.8],
}

export function roadOpacity(id: string, k = 1): maplibregl.ExpressionSpecification {
  const stops = ROAD_LAYERS[id].map((v, i) => (i % 2 ? v * k : v))
  return ['interpolate', ['linear'], ['zoom'], ...stops] as maplibregl.ExpressionSpecification
}

export const mapStyle: StyleSpecification = {
  version: 8,
  glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
  sources: {
    osm: {
      type: 'vector',
      url: 'https://tiles.openfreemap.org/planet',
      attribution: '© OpenStreetMap · OpenFreeMap',
    },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#000' } },
    {
      id: 'park',
      type: 'fill',
      source: 'osm',
      'source-layer': 'park',
      paint: { 'fill-color': '#0a0603' },
    },
    {
      id: 'water',
      type: 'fill',
      source: 'osm',
      'source-layer': 'water',
      paint: { 'fill-color': '#05070b' },
    },
    {
      // korfez kiyisi: suyun kenari ince turuncu bir cizgi
      id: 'water-edge',
      type: 'line',
      source: 'osm',
      'source-layer': 'water',
      paint: { 'line-color': ACCENT_BASE, 'line-opacity': 0.35, 'line-width': 0.8 },
    },
    {
      id: 'roads-minor',
      type: 'line',
      source: 'osm',
      'source-layer': 'transportation',
      filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'tertiary']]],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ACCENT,
        'line-opacity': roadOpacity('roads-minor'),
        'line-width': ['interpolate', ['linear'], ['zoom'], 12, 0.3, 18, 2],
      },
    },
    {
      id: 'roads-major',
      type: 'line',
      source: 'osm',
      'source-layer': 'transportation',
      filter: ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary', 'secondary']]],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ACCENT,
        'line-opacity': roadOpacity('roads-major'),
        'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.6, 18, 5],
        'line-blur': 0.6,
      },
    },
    {
      id: 'rail',
      type: 'line',
      source: 'osm',
      'source-layer': 'transportation',
      filter: ['==', ['get', 'class'], 'rail'],
      paint: { 'line-color': '#e91e8c', 'line-opacity': 0.35, 'line-width': 0.8, 'line-dasharray': [2, 2] },
    },
    {
      id: 'buildings-3d',
      type: 'fill-extrusion',
      source: 'osm',
      'source-layer': 'building',
      minzoom: 13,
      paint: {
        // yukseldikce turuncuya isinan koyu bloklar
        'fill-extrusion-color': [
          'interpolate', ['linear'], ['coalesce', ['get', 'render_height'], 8],
          0, '#14100d', 30, '#2a1608', 80, '#5a2a0c',
        ],
        'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 8],
        'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
        'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0, 14, 0.92],
        'fill-extrusion-vertical-gradient': true,
      },
    },
    {
      id: 'place-labels',
      type: 'symbol',
      source: 'osm',
      'source-layer': 'place',
      filter: ['in', ['get', 'class'], ['literal', ['city', 'town', 'suburb', 'quarter', 'neighbourhood']]],
      layout: {
        'text-field': ['coalesce', ['get', 'name:tr'], ['get', 'name']],
        'text-font': LABEL_FONT,
        'text-size': ['match', ['get', 'class'], 'city', 15, 'town', 13, 11],
        'text-transform': 'uppercase',
        'text-letter-spacing': 0.18,
      },
      paint: { 'text-color': '#ffffff9e', 'text-halo-color': '#000', 'text-halo-width': 1.4 },
    },
  ],
}
