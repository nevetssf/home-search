// Ingestion entry points: paste a Zillow URL, upload a Redfin CSV, or add a
// property manually. Manual entry is the graceful fallback (PLAN.md §6).
import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { createProperty, ingestRealtorSearch, ingestRedfinCsv, ingestUrl } from '../api'

export default function AddPropertyBar({ onChange }) {
  const nav = useNavigate()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [search, setSearch] = useState({ location: '', beds_min: '', price_min: '', price_max: '' })

  const addFromUrl = async (e) => {
    e.preventDefault()
    if (!url) return
    setBusy(true); setMsg('')
    try {
      const res = await ingestUrl(url)
      setUrl('')
      onChange?.()
      if (res.property_ids?.[0]) nav(`/property/${res.property_ids[0]}`)
    } catch (err) {
      const status = err.response?.status
      setMsg(
        status === 400 ? 'Paste a zillow.com or redfin.com listing URL.'
        : status === 502 ? 'Site blocked the fetch (try from your home network) — or add manually.'
        : 'Could not fetch that listing.'
      )
    } finally {
      setBusy(false)
    }
  }

  const uploadCsv = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy(true); setMsg('')
    try {
      const res = await ingestRedfinCsv(file)
      setMsg(`Imported ${res.created} new, updated ${res.updated}.`)
      onChange?.()
    } catch {
      setMsg('CSV import failed.')
    } finally {
      setBusy(false)
      e.target.value = ''
    }
  }

  const searchRealtor = async (e) => {
    e.preventDefault()
    if (!search.location) return
    setBusy(true); setMsg('')
    try {
      // Drop blanks; coerce the numeric fields the backend expects as ints.
      const params = { location: search.location }
      for (const k of ['beds_min', 'price_min', 'price_max']) {
        if (search[k] !== '') params[k] = Number(search[k])
      }
      const res = await ingestRealtorSearch(params)
      setMsg(`Realtor.com: ${res.created} new, ${res.updated} updated.`)
      onChange?.()
    } catch (err) {
      setMsg(
        err.response?.status === 503
          ? 'Realtor search unavailable (blocked or disabled) — try from your home network.'
          : 'Realtor search failed.'
      )
    } finally {
      setBusy(false)
    }
  }

  const addManual = async () => {
    const p = await createProperty({ source: 'manual', status: 'for_sale' })
    nav(`/property/${p.id}`)
  }

  return (
    <div className="addbar">
      <form onSubmit={addFromUrl} className="addbar-zillow">
        <input
          placeholder="Paste a Zillow or Redfin listing URL…" value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <button disabled={busy} type="submit">{busy ? 'Fetching…' : 'Add from URL'}</button>
      </form>
      <form onSubmit={searchRealtor} className="addbar-realtor">
        <input
          placeholder="Search Realtor.com area (e.g. Boulder, CO or 80302)…"
          value={search.location}
          onChange={(e) => setSearch({ ...search, location: e.target.value })}
        />
        <input
          type="number" min="0" placeholder="Beds" style={{ width: '4.5em' }}
          value={search.beds_min}
          onChange={(e) => setSearch({ ...search, beds_min: e.target.value })}
        />
        <input
          type="number" min="0" placeholder="Min $" style={{ width: '7em' }}
          value={search.price_min}
          onChange={(e) => setSearch({ ...search, price_min: e.target.value })}
        />
        <input
          type="number" min="0" placeholder="Max $" style={{ width: '7em' }}
          value={search.price_max}
          onChange={(e) => setSearch({ ...search, price_max: e.target.value })}
        />
        <button disabled={busy} type="submit">{busy ? 'Searching…' : 'Search area'}</button>
      </form>
      <label className="filelabel">
        Import Redfin CSV
        <input type="file" accept=".csv" hidden onChange={uploadCsv} disabled={busy} />
      </label>
      <button onClick={addManual} disabled={busy}>+ Manual</button>
      {msg && <span className="addbar-msg">{msg}</span>}
    </div>
  )
}
