// Ingestion entry points for adding individual properties: paste a Zillow/Redfin
// URL, upload a Redfin CSV, or add one manually. Area/criteria searching lives
// in the ⌕ Search pop-up (top nav), not here.
import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { createProperty, ingestRedfinCsv, ingestUrl } from '../api'

export default function AddPropertyBar({ onChange }) {
  const nav = useNavigate()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

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
      <label className="filelabel">
        Import Redfin CSV
        <input type="file" accept=".csv" hidden onChange={uploadCsv} disabled={busy} />
      </label>
      <button onClick={addManual} disabled={busy}>+ Manual</button>
      {msg && <span className="addbar-msg">{msg}</span>}
    </div>
  )
}
