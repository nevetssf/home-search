import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  addNote, deleteNote, deleteProperty, getDistances, getProperty,
  refreshDistances, updateNote, updateProperty,
} from '../api'
import CriteriaPanel from '../components/CriteriaPanel'
import MediaGallery from '../components/MediaGallery'

const STATUSES = ['for_sale', 'pending', 'sold', 'off_market', 'coming_soon']
const fmtPrice = (p) => (p == null ? '—' : `$${Number(p).toLocaleString()}`)
const fmtMins = (s) => (s == null ? '—' : `${Math.round(s / 60)} min`)
const fmtMiles = (m) => (m == null ? '—' : `${(m / 1609).toFixed(1)} mi`)

const FIELDS = [
  ['address', 'Address'], ['city', 'City'], ['state', 'State'], ['zip', 'Zip'],
  ['price', 'Price'], ['beds', 'Beds'], ['baths', 'Baths'], ['sqft', 'Sqft'],
  ['lot_size', 'Lot (acres)'], ['year_built', 'Year built'],
  ['property_type', 'Type'], ['latitude', 'Lat'], ['longitude', 'Lng'],
]

export default function Detail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [p, setP] = useState(null)
  const [distances, setDistances] = useState([])
  const [note, setNote] = useState('')
  const [distMsg, setDistMsg] = useState('')

  const load = () => getProperty(id).then(setP)
  useEffect(() => { load(); getDistances(id).then(setDistances) }, [id])

  if (!p) return <p>Loading…</p>

  const saveField = async (key, value) => {
    const num = ['price', 'beds', 'baths', 'sqft', 'lot_size', 'year_built',
      'latitude', 'longitude'].includes(key)
    await updateProperty(id, { [key]: num ? (value === '' ? null : Number(value)) : value })
    load()
  }

  const changeStatus = async (status) => { await updateProperty(id, { status }); load() }

  const postNote = async (e) => {
    e.preventDefault()
    if (!note.trim()) return
    await addNote(id, note)
    setNote('')
    load()
  }

  const doRefreshDistances = async () => {
    setDistMsg('Computing…')
    try {
      setDistances(await refreshDistances(id))
      setDistMsg('')
    } catch (err) {
      setDistMsg(err.response?.status === 503
        ? 'Google Maps key not configured.'
        : err.response?.status === 400 ? 'Add coordinates first.' : 'Failed.')
    }
  }

  const remove = async () => {
    if (confirm('Delete this property permanently?')) {
      await deleteProperty(id)
      nav('/')
    }
  }

  return (
    <div className="detail">
      <div className="detail-head">
        <h2>{p.address || `Property #${p.id}`}</h2>
        <div>
          <select value={p.status} onChange={(e) => changeStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
          </select>
          {p.source_url && <a href={p.source_url} target="_blank" rel="noreferrer" className="ext">source ↗</a>}
          <button className="link-btn danger" onClick={remove}>Delete</button>
        </div>
      </div>
      <p className="muted">
        {p.city}{p.state ? `, ${p.state}` : ''} · {fmtPrice(p.price)} ·
        {' '}{p.beds ?? '—'} bd / {p.baths ?? '—'} ba · source: {p.source}
      </p>

      <div className="detail-grid">
        <div className="col">
          <MediaGallery propertyId={id} />

          <section className="card">
            <h3>Facts</h3>
            <div className="facts">
              {FIELDS.map(([key, label]) => (
                <label key={key} className="crow">
                  <span>{label}</span>
                  <input
                    defaultValue={p[key] ?? ''}
                    onBlur={(e) => e.target.value !== String(p[key] ?? '') && saveField(key, e.target.value)}
                  />
                </label>
              ))}
            </div>
          </section>

          {p.description && (
            <section className="card">
              <h3>Description</h3>
              <p>{p.description}</p>
            </section>
          )}
        </div>

        <div className="col">
          <section className="card"><CriteriaPanel propertyId={id} /></section>

          <section className="card">
            <div className="score-header">
              <h3>Distances</h3>
              <button onClick={doRefreshDistances}>Refresh</button>
            </div>
            {distMsg && <p className="muted">{distMsg}</p>}
            <table className="grid sm">
              <tbody>
                {distances.map((d) => (
                  <tr key={d.id}>
                    <td>{d.category.startsWith('poi:') ? `📍 ${d.place_name}` : d.category}</td>
                    <td>{d.place_name}</td>
                    <td>{fmtMiles(d.distance_meters)}</td>
                    <td>{fmtMins(d.duration_seconds)}</td>
                  </tr>
                ))}
                {distances.length === 0 && <tr><td className="muted">None computed.</td></tr>}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h3>Notes</h3>
            <form onSubmit={postNote} className="noteform">
              <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note…" />
              <button type="submit">Add</button>
            </form>
            <ul className="notes">
              {p.notes?.map((n) => (
                <NoteItem key={n.id} note={n} propertyId={id} onChange={load} />
              ))}
            </ul>
          </section>

          <section className="card">
            <h3>Status timeline</h3>
            <ul className="timeline">
              {p.status_history?.map((h) => (
                <li key={h.id}>
                  <span className={`badge ${h.status}`}>{h.status.replace('_', ' ')}</span>
                  <span className="muted"> {new Date(h.observed_at).toLocaleDateString()} ({h.source})</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </div>
  )
}

function NoteItem({ note, propertyId, onChange }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(note.body)

  const save = async () => {
    const body = draft.trim()
    if (!body) return
    await updateNote(propertyId, note.id, body)
    setEditing(false)
    onChange()
  }
  const remove = async () => {
    if (confirm('Delete this note?')) {
      await deleteNote(propertyId, note.id)
      onChange()
    }
  }

  if (editing) {
    return (
      <li>
        <textarea className="note-edit" value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus />
        <span className="note-actions">
          <button className="link-btn" onClick={save}>save</button>
          <button className="link-btn" onClick={() => { setDraft(note.body); setEditing(false) }}>cancel</button>
        </span>
      </li>
    )
  }
  return (
    <li>
      {note.body}
      <span className="muted"> · {new Date(note.created_at).toLocaleDateString()}</span>
      <span className="note-actions">
        <button className="link-btn" onClick={() => setEditing(true)}>edit</button>
        <button className="link-btn danger" onClick={remove}>delete</button>
      </span>
    </li>
  )
}
