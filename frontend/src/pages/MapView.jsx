// Map view (Leaflet + OpenStreetMap, no API key). Two region sets, persisted
// across views via the regions store:
//   • SEARCH (blue) — "Search this area" pulls listings from these regions.
//   • FILTER (orange) — narrows which properties show in the List view.
// Draw with the toolbar (top-right) into whichever set is active; toggle each
// set's visibility; click a region to remove it.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Circle, CircleMarker, MapContainer, Polygon, Popup, Rectangle, TileLayer,
  useMap, useMapEvents,
} from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet-draw'
import 'leaflet-draw/dist/leaflet.draw.css'
import { listProperties, searchRegion } from '../api'
import { useViewState } from '../regions'
import { useFilterSets } from '../filterSets'
import { passesValueFilters, useFilterColumns } from '../filters'
import { inAnyShape } from '../geo'
import FilterSetPicker from '../components/FilterSetPicker'

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

// Persist the map's center/zoom so the view is restored on return (and reload).
const VIEW_KEY = 'home-search:mapview'
function loadView() {
  try {
    const v = JSON.parse(localStorage.getItem(VIEW_KEY))
    return v && Array.isArray(v.center) && typeof v.zoom === 'number' ? v : null
  } catch {
    return null
  }
}
function ViewPersist() {
  const save = (map) =>
    localStorage.setItem(
      VIEW_KEY,
      JSON.stringify({ center: [map.getCenter().lat, map.getCenter().lng], zoom: map.getZoom() })
    )
  const map = useMapEvents({ moveend: () => save(map), zoomend: () => save(map) })
  return null
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
  const { search, setSearch, mapFade, setMapFade, searchCriteria, dataVersion } = useViewState()
  const {
    valueFilters, setValueFilters, filterRegions: filter, setFilterRegions: setFilter,
  } = useFilterSets()
  const columns = useFilterColumns()
  const [rows, setRows] = useState([])
  const [active, setActive] = useState('search')  // which set new shapes go into
  const [show, setShow] = useState({ search: true, filter: true })
  const [showFilters, setShowFilters] = useState(false)
  const [searching, setSearching] = useState(false)
  const [msg, setMsg] = useState('')
  const savedView = useRef(loadView())  // last viewport, read once on mount

  const load = useCallback(
    () => listProperties({ with_criteria: true }).then(setRows).catch(() => {}),
    []
  )
  useEffect(() => { load() }, [load, dataVersion])

  // Same match rule as the List view: passes value filters AND filter regions.
  const passes = useMemo(
    () => (p) =>
      passesValueFilters(p, columns, valueFilters) &&
      (filter.length === 0 || inAnyShape(filter, p.latitude, p.longitude)),
    [columns, valueFilters, filter]
  )
  const activeFilterCount = Object.values(valueFilters).filter(Boolean).length

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
      const res = await searchRegion(search, searchCriteria || {})
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
  const setFilterVal = (key, val) => setValueFilters({ ...valueFilters, [key]: val })

  return (
    <div className="mapview">
      <div className="region-bar">
        <FilterSetPicker />
        <button onClick={() => setShowFilters((v) => !v)}>
          {showFilters ? 'Hide filters' : 'Filters'}{activeFilterCount ? ` (${activeFilterCount})` : ''}
        </button>
        <label className="inline-check">
          <input type="checkbox" checked={mapFade} onChange={(e) => setMapFade(e.target.checked)} />
          fade non-matches (uncheck to hide)
        </label>
        {(activeFilterCount > 0 || filter.length > 0) && (
          <button className="link-btn" onClick={() => { setValueFilters({}); setFilter([]) }}>
            clear all filters
          </button>
        )}
      </div>
      {showFilters && (
        <div className="filter-panel">
          {columns.map((c) => (
            <label key={c.key} className="filter-field">
              <span>{c.label}</span>
              <input
                value={valueFilters[c.key] || ''}
                placeholder={c.type === 'number' ? '>0' : 'filter'}
                onChange={(e) => setFilterVal(c.key, e.target.value)}
              />
            </label>
          ))}
        </div>
      )}
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
          <span className="muted">· filter regions narrow List + Map ({filter.length})</span>
        )}
        {msg && <span className="region-msg">{msg}</span>}
      </div>

      <MapContainer
        center={savedView.current?.center || [39.5, -98.35]}
        zoom={savedView.current?.zoom ?? 4}
        className="map"
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ViewPersist />
        <DrawTools onCreate={addToActive} />
        {/* Auto-fit to properties only on the first-ever visit; afterward, the
            user's saved viewport wins. */}
        {!savedView.current && <FitBounds points={points} />}
        {show.search && <RegionLayer shapes={search} color={SET_COLOR.search} onRemove={removeFrom('search')} />}
        {show.filter && <RegionLayer shapes={filter} color={SET_COLOR.filter} onRemove={removeFrom('filter')} />}
        {located.map((p) => {
          const ok = passes(p)
          if (!ok && !mapFade) return null  // hide mode: drop non-matches
          return (
          <CircleMarker
            key={p.id}
            center={[p.latitude, p.longitude]}
            radius={8}
            pathOptions={{
              color: '#fff', weight: 2, opacity: ok ? 1 : 0.7,
              fillColor: STATUS_COLOR[p.status] || '#555', fillOpacity: ok ? 1 : 0.45,
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
          )
        })}
      </MapContainer>
    </div>
  )
}
