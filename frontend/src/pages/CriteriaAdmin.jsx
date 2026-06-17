// Criteria admin: add/edit/reorder criteria, set type/unit/scale/weight
// (PLAN.md §8). A new criterion is pure data — no code change.
import { useEffect, useState } from 'react'
import { createCriterion, deleteCriterion, listCriteria, updateCriterion } from '../api'

const TYPES = ['boolean', 'number', 'rating', 'enum', 'text']
const blank = {
  name: '', value_type: 'boolean', unit: '', is_subjective: false,
  weight: 1, scale_min: 1, scale_max: 5, options: '',
}

export default function CriteriaAdmin() {
  const [criteria, setCriteria] = useState([])
  const [form, setForm] = useState(blank)
  const [error, setError] = useState('')

  const load = () => listCriteria(true).then(setCriteria)
  useEffect(() => { load() }, [])

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    const body = {
      name: form.name,
      value_type: form.value_type,
      unit: form.unit || null,
      is_subjective: form.is_subjective,
      weight: Number(form.weight),
    }
    if (form.value_type === 'rating') {
      body.scale_min = Number(form.scale_min)
      body.scale_max = Number(form.scale_max)
    }
    if (form.value_type === 'enum') {
      body.options = form.options.split(',').map((s) => s.trim()).filter(Boolean)
    }
    try {
      await createCriterion(body)
      setForm(blank)
      load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create criterion')
    }
  }

  const toggleActive = async (c) => { await updateCriterion(c.id, { active: !c.active }); load() }
  const remove = async (c) => { if (confirm(`Delete “${c.name}”?`)) { await deleteCriterion(c.id); load() } }

  return (
    <div className="criteria-admin">
      <h2>Criteria</h2>
      <form className="card crit-form" onSubmit={submit}>
        <input
          placeholder="Name" value={form.name} required
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <select value={form.value_type} onChange={(e) => setForm({ ...form, value_type: e.target.value })}>
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        {form.value_type === 'number' && (
          <input placeholder="unit (e.g. acres)" value={form.unit}
            onChange={(e) => setForm({ ...form, unit: e.target.value })} />
        )}
        {form.value_type === 'rating' && (
          <>
            <input type="number" placeholder="min" value={form.scale_min}
              onChange={(e) => setForm({ ...form, scale_min: e.target.value })} style={{ width: 70 }} />
            <input type="number" placeholder="max" value={form.scale_max}
              onChange={(e) => setForm({ ...form, scale_max: e.target.value })} style={{ width: 70 }} />
          </>
        )}
        {form.value_type === 'enum' && (
          <input placeholder="options, comma-separated" value={form.options}
            onChange={(e) => setForm({ ...form, options: e.target.value })} />
        )}
        <label className="inline-check">
          <input type="checkbox" checked={form.is_subjective}
            onChange={(e) => setForm({ ...form, is_subjective: e.target.checked })} />
          subjective (per-user rating)
        </label>
        <input type="number" step="0.5" placeholder="weight" value={form.weight}
          onChange={(e) => setForm({ ...form, weight: e.target.value })} style={{ width: 80 }} title="weight" />
        <button type="submit">Add criterion</button>
        {error && <span className="error">{error}</span>}
      </form>

      <table className="grid">
        <thead>
          <tr><th>Name</th><th>Type</th><th>Unit/Scale</th><th>Subjective</th><th>Weight</th><th>Active</th><th></th></tr>
        </thead>
        <tbody>
          {criteria.map((c) => (
            <tr key={c.id} className={c.active ? '' : 'inactive'}>
              <td>{c.name}</td>
              <td>{c.value_type}</td>
              <td>{c.value_type === 'rating' ? `${c.scale_min}–${c.scale_max}`
                : c.value_type === 'enum' ? (c.options || []).join(', ')
                : c.unit || '—'}</td>
              <td>{c.is_subjective ? 'yes' : 'no'}</td>
              <td>{c.weight}</td>
              <td><button className="link-btn" onClick={() => toggleActive(c)}>{c.active ? '✓' : '—'}</button></td>
              <td><button className="link-btn danger" onClick={() => remove(c)}>delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
