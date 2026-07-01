// Search-parameters pop-up. Holds the shared search criteria (price/beds/…)
// and runs a search over either the map-drawn search regions OR a typed
// city/ZIP. Criteria are persisted in the view store. Realtor.com only for now.
import { useState } from 'react'
import { ingestRealtorSearch, searchRegion } from '../api'
import { useViewState } from '../regions'

const STATUSES = [
  ['for_sale', 'For sale'], ['pending', 'Pending'], ['sold', 'Sold'],
]
const numOrNull = (v) => (v === '' || v == null ? null : Number(v))

export default function SearchModal({ onClose }) {
  const { search: regions, searchCriteria, setSearchCriteria, bumpData } = useViewState()
  const [c, setC] = useState({ listing_type: 'for_sale', ...searchCriteria })
  const [loc, setLoc] = useState('')
  const [radius, setRadius] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const set = (k, v) => setC((prev) => ({ ...prev, [k]: v }))

  // Assemble the criteria payload the backend understands.
  const criteria = () => ({
    listing_type: c.listing_type || 'for_sale',
    price_min: numOrNull(c.price_min),
    price_max: numOrNull(c.price_max),
    beds_min: numOrNull(c.beds_min),
    baths_min: numOrNull(c.baths_min),
    sqft_min: numOrNull(c.sqft_min),
    sqft_max: numOrNull(c.sqft_max),
  })

  const run = async () => {
    setBusy(true); setMsg('')
    const crit = criteria()
    setSearchCriteria(crit)  // persist cleaned criteria for the map/Update buttons
    try {
      let res
      if (loc.trim()) {
        res = await ingestRealtorSearch({ location: loc.trim(), radius: numOrNull(radius) || undefined, ...crit })
      } else if (regions.length) {
        res = await searchRegion(regions, crit)
      } else {
        setBusy(false)
        setMsg('Draw a search region on the Map, or enter a city / ZIP above.')
        return
      }
      const capped = (res.errors || []).find((e) => e.includes('smaller regions') || e.includes('areas'))
      setMsg(`Added ${res.created} new, ${res.updated} updated${res.skipped ? `, ${res.skipped} outside area` : ''}.${capped ? ' (search area was capped)' : ''}`)
      bumpData()  // reload List/Map
    } catch (e) {
      setMsg(e.response?.status === 503 ? 'Search unavailable (Realtor disabled).' : 'Search failed.')
    } finally {
      setBusy(false)
    }
  }

  const field = (label, key, placeholder) => (
    <label className="search-field">
      <span>{label}</span>
      <input type="number" placeholder={placeholder} value={c[key] ?? ''}
        onChange={(e) => set(key, e.target.value)} />
    </label>
  )

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Search for properties</h3>
          <button className="link-btn" onClick={onClose}>✕</button>
        </div>

        <h4>Area</h4>
        <p className="muted">
          {regions.length
            ? `Using ${regions.length} region${regions.length > 1 ? 's' : ''} drawn on the Map.`
            : 'No map regions drawn — draw them on the Map tab, or search a city/ZIP:'}
        </p>
        <div className="search-row">
          <label className="search-field wide">
            <span>City / ZIP (optional)</span>
            <input placeholder="e.g. Santa Rosa, CA or 95404" value={loc}
              onChange={(e) => setLoc(e.target.value)} />
          </label>
          <label className="search-field">
            <span>Radius (mi)</span>
            <input type="number" placeholder="0" value={radius}
              onChange={(e) => setRadius(e.target.value)} />
          </label>
        </div>
        <p className="muted small">A city/ZIP here overrides the map regions for this search.</p>

        <h4>Filters</h4>
        <div className="search-grid">
          <label className="search-field">
            <span>Status</span>
            <select value={c.listing_type || 'for_sale'} onChange={(e) => set('listing_type', e.target.value)}>
              {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          {field('Min price', 'price_min', '$')}
          {field('Max price', 'price_max', '$')}
          {field('Beds (min)', 'beds_min', '0')}
          {field('Baths (min)', 'baths_min', '0')}
          {field('Min sqft', 'sqft_min', '0')}
          {field('Max sqft', 'sqft_max', '0')}
        </div>

        <div className="modal-foot">
          {msg && <span className="muted">{msg}</span>}
          <span className="spacer" />
          <button onClick={onClose}>Close</button>
          <button className="primary" onClick={run} disabled={busy}>
            {busy ? 'Searching…' : 'Search'}
          </button>
        </div>
      </div>
    </div>
  )
}
