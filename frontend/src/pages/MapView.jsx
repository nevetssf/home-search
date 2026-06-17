// Map view: pins colored by status, click → detail. The Maps JavaScript API
// needs a *browser* key (referrer-restricted) — separate from the server-side
// key used for Places/Distance Matrix. Without it we degrade to a coordinate
// list rather than failing.
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { listProperties } from '../api'
import FilterBar, { paramsToQuery } from '../components/FilterBar'

const MAPS_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY
const STATUS_COLOR = {
  for_sale: '#2e7d32', pending: '#f9a825', sold: '#c62828',
  off_market: '#757575', coming_soon: '#1565c0',
}

let mapsPromise = null
function loadMaps() {
  if (!MAPS_KEY) return Promise.reject(new Error('no key'))
  if (mapsPromise) return mapsPromise
  mapsPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = `https://maps.googleapis.com/maps/api/js?key=${MAPS_KEY}`
    s.async = true
    s.onload = resolve
    s.onerror = reject
    document.head.appendChild(s)
  })
  return mapsPromise
}

export default function MapView() {
  const [params] = useSearchParams()
  const [rows, setRows] = useState([])
  const [ready, setReady] = useState(false)
  const mapRef = useRef(null)
  const mapObj = useRef(null)
  const markers = useRef([])
  const nav = useNavigate()

  useEffect(() => {
    listProperties(paramsToQuery(params)).then(setRows)
  }, [params])

  useEffect(() => {
    loadMaps().then(() => setReady(true)).catch(() => setReady(false))
  }, [])

  useEffect(() => {
    if (!ready || !mapRef.current || !window.google) return
    if (!mapObj.current) {
      mapObj.current = new google.maps.Map(mapRef.current, {
        center: { lat: 38.4, lng: -122.8 }, zoom: 9,
      })
    }
    markers.current.forEach((m) => m.setMap(null))
    markers.current = []
    const bounds = new google.maps.LatLngBounds()
    rows.filter((p) => p.latitude && p.longitude).forEach((p) => {
      const pos = { lat: p.latitude, lng: p.longitude }
      const marker = new google.maps.Marker({
        position: pos, map: mapObj.current, title: p.address || `#${p.id}`,
        icon: {
          path: google.maps.SymbolPath.CIRCLE, scale: 8,
          fillColor: STATUS_COLOR[p.status] || '#555', fillOpacity: 1,
          strokeColor: '#fff', strokeWeight: 2,
        },
      })
      marker.addListener('click', () => nav(`/property/${p.id}`))
      markers.current.push(marker)
      bounds.extend(pos)
    })
    if (markers.current.length) mapObj.current.fitBounds(bounds)
  }, [ready, rows, nav])

  return (
    <div>
      <FilterBar />
      {MAPS_KEY ? (
        <div ref={mapRef} className="map" />
      ) : (
        <div className="card">
          <p className="muted">
            Set <code>VITE_GOOGLE_MAPS_API_KEY</code> (a browser Maps JS key) to
            enable the map. Properties with coordinates:
          </p>
          <ul>
            {rows.filter((p) => p.latitude).map((p) => (
              <li key={p.id}>
                <a onClick={() => nav(`/property/${p.id}`)}>{p.address || `#${p.id}`}</a>
                {' — '}{p.latitude.toFixed(4)}, {p.longitude.toFixed(4)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
