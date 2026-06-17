// Ingestion entry points: paste a Zillow URL, upload a Redfin CSV, or add a
// property manually. Manual entry is the graceful fallback (PLAN.md §6).
import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { createProperty, ingestRedfinCsv, ingestZillowUrl } from '../api'

export default function AddPropertyBar({ onChange }) {
  const nav = useNavigate()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const addZillow = async (e) => {
    e.preventDefault()
    if (!url) return
    setBusy(true); setMsg('')
    try {
      const res = await ingestZillowUrl(url)
      setUrl('')
      onChange?.()
      if (res.property_ids?.[0]) nav(`/property/${res.property_ids[0]}`)
    } catch (err) {
      setMsg(err.response?.status === 503
        ? 'Zillow API key not configured — add manually instead.'
        : 'Could not fetch that listing.')
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
      <form onSubmit={addZillow} className="addbar-zillow">
        <input
          placeholder="Paste a Zillow listing URL…" value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <button disabled={busy} type="submit">Add from Zillow</button>
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
