// Map view (Leaflet + OpenStreetMap, no API key). Two region sets, persisted
// across views via the regions store:
//   • SEARCH (blue) — "Search this area" pulls listings from these regions.
//   • FILTER (orange) — narrows which properties show in the List view.
// Draw with the toolbar (top-right) into whichever set is active; toggle each
// set's visibility; click a region to remove it.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Circle, CircleMarker, MapContainer, Polygon, Popup, Rectangle, TileLayer, useMap,
} from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet-draw'
import 'leaflet-draw/dist/leaflet.draw.css'
import { listProperties, searchRegion } from '../api'
import { useRegions } from '../regions'
import FilterBar, { paramsToQuery } from '../components/FilterBar'

const STATUS_COLOR = {
  for_sale: '#2e7d32', pending: '#f9a825', sold: '#c62828',
  off_market: '#757575', coming_soon: '#1565c0',
}
const SET_COLOR = { search: '#1565c0', filter: '#e65100' }
const fmtPrice = (p) => (p == null ? '—' : `$${Number(p).toLocaleString()}`)

// A freshly drawn Leaflet layer → our region payload ([lat, lng] coords).
function layerToShape(layer) {
  if (layer instanceof L.Circle) {
    const c = layer.getLatLng()
    return { kind: 'circle', center: [c.lat, c.lng], radius_mi: layer.getRadius() / 1609.344 }
  }
  if (layer instanceof L.Rectangle) {
    const b = layer.getBounds()
    return { kind: 'rectangle', bbox: [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()] }
  }
  if (layer instanceof L.Polygon) {
    return { kind: 'polygon', points: layer.getLatLngs()[0].map((p) => [p.lat, p.lng]) }
  }
  return null
}

// leaflet-draw toolbar (draw-only — shapes are rendered from the store, not
// kept inside leaflet-draw, which sidesteps its single-edit-group limitation).
function DrawTools({ onCreate }) {
  const map = useMap()
  const cb = useRef(onCreate)
  cb.current = onCreate
  useEffect(() => {
    const control = new L.Control.Draw({
      position: 'topright',
      draw: {
        rectangle: { showArea: false },  // showArea triggers a known readableArea crash
        circle: { showArea: false },
        polygon: { showArea: false },
        marker: false, polyline: false, circlemarker: false,
      },
    })
    map.addControl(control)
    const onCreated = (e) => { const s = layerToShape(e.layer); if (s) cb.current(s) }
    map.on(L.Draw.Event.CREATED, onCreated)
    return () => { map.off(L.Draw.Event.CREATED, onCreated); map.removeControl(control) }
  }, [map])
  return null
}

// Render a region set from the store as colored, removable overlays.
function RegionLayer({ shapes, color, onRemove }) {
  return shapes.map((s, i) => {
    const opts = { pathOptions: { color, weight: 2, fillOpacity: 0.08 } }
    const popup = (
      <Popup>
        <button className="link-btn danger" onClick={() => onRemove(i)}>remove region</button>
      </Popup>
    )
    if (s.kind === 'rectangle') {
      const [a, b, c, d] = s.bbox
      return <Rectangle key={i} bounds={[[a, b], [c, d]]} {...opts}>{popup}</Rectangle>
    }
    if (s.kind === 'circle') {
      return <Circle key={i} center={s.center} radius={s.radius_mi * 1609.344} {...opts}>{popup}</Circle>
    }
    if (s.kind === 'polygon') {
      return <Polygon key={i} positions={s.points} {...opts}>{popup}</Polygon>
    }
    return null
  })
}

function FitBounds({ points }) {
  const map = useMap()
  const done = useRef(false)
  useEffect(() => {
    if (done.current || !points.length) return  // only auto-fit once, don't fight the user
    done.current = true
    if (points.length === 1) map.setView(points[0], 13)
    else map.fitBounds(points, { padding: [40, 40] })
  }, [points, map])
  return null
}

export default function MapView() {
  const [params] = useSearchParams()
  const { search, setSearch, filter, setFilter } = useRegions()
  const [rows, setRows] = useState([])
  const [active, setActive] = useState('search')  // which set new shapes go into
  const [show, setShow] = useState({ search: true, filter: true })
  const [searching, setSearching] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(
    () => listProperties(paramsToQuery(params)).then(setRows).catch(() => {}),
    [params]
  )
  useEffect(() => { load() }, [load])

  const addToActive = useCallback(
    (shape) => (active === 'search' ? setSearch((s) => [...s, shape]) : setFilter((s) => [...s, shape])),
    [active, setSearch, setFilter]
  )
  const removeFrom = (set) => (i) =>
    (set === 'search' ? setSearch : setFilter)((s) => s.filter((_, j) => j !== i))

  const runSearch = async () => {
    if (!search.length) return
    setSearching(true)
    setMsg('Searching Realtor.com within the search region(s)…')
    try {
      const res = await searchRegion(search)
      const capped = (res.errors || []).find((e) => e.includes('smaller regions'))
      const bits = [`added ${res.created} new`, `${res.updated} updated`]
      if (res.skipped) bits.push(`${res.skipped} outside region`)
      setMsg(bits.join(', ') + (capped ? ` — ${capped}` : ''))
      await load()
    } catch (e) {
      setMsg(e.response?.status === 503 ? 'Realtor search is unavailable.' : 'Region search failed.')
    } finally {
      setSearching(false)
    }
  }

  const located = rows.filter((p) => p.latitude != null && p.longitude != null)
  const points = located.map((p) => [p.latitude, p.longitude])

  return (
    <div>
      <FilterBar />
      <div className="region-bar">
        <span className="region-mode">
          Draw into:
          {['search', 'filter'].map((s) => (
            <button
              key={s}
              className={active === s ? 'chip on' : 'chip'}
              style={active === s ? { background: SET_COLOR[s], borderColor: SET_COLOR[s] } : { borderColor: SET_COLOR[s] }}
              onClick={() => setActive(s)}
            >
              {s}
            </button>
          ))}
        </span>
        <label className="inline-check">
          <input type="checkbox" checked={show.search} onChange={(e) => setShow((v) => ({ ...v, search: e.target.checked }))} />
          <span style={{ color: SET_COLOR.search }}>● search ({search.length})</span>
        </label>
        <label className="inline-check">
          <input type="checkbox" checked={show.filter} onChange={(e) => setShow((v) => ({ ...v, filter: e.target.checked }))} />
          <span style={{ color: SET_COLOR.filter }}>● filter ({filter.length})</span>
        </label>
        <button onClick={runSearch} disabled={!search.length || searching}>
          {searching ? 'Searching…' : `Search this area${search.length ? ` (${search.length})` : ''}`}
        </button>
        {filter.length > 0 && (
          <span className="muted">· filter narrows the List view to {filter.length} region(s)</span>
        )}
        {msg && <span className="region-msg">{msg}</span>}
      </div>

      <MapContainer center={[39.5, -98.35]} zoom={4} className="map" scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <DrawTools onCreate={addToActive} />
        <FitBounds points={points} />
        {show.search && <RegionLayer shapes={search} color={SET_COLOR.search} onRemove={removeFrom('search')} />}
        {show.filter && <RegionLayer shapes={filter} color={SET_COLOR.filter} onRemove={removeFrom('filter')} />}
        {located.map((p) => (
          <CircleMarker
            key={p.id}
            center={[p.latitude, p.longitude]}
            radius={8}
            pathOptions={{
              color: '#fff', weight: 2,
              fillColor: STATUS_COLOR[p.status] || '#555', fillOpacity: 1,
            }}
          >
            <Popup>
              <strong>{p.address || `Property #${p.id}`}</strong><br />
              {p.city}{p.state ? `, ${p.state}` : ''}<br />
              {fmtPrice(p.price)} · {p.beds ?? '—'} bd / {p.baths ?? '—'} ba<br />
              <span className={`badge ${p.status}`}>{p.status?.replace('_', ' ')}</span>
              {' '}<Link to={`/property/${p.id}`}>details →</Link>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}
