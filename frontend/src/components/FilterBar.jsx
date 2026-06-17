// Composable filter bar shared by List and Map. State lives in the URL query
// string (via useSearchParams) so views are shareable/bookmarkable (PLAN.md §8).
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listTags } from '../api'

const STATUSES = ['', 'for_sale', 'pending', 'sold', 'off_market', 'coming_soon']

export default function FilterBar() {
  const [params, setParams] = useSearchParams()
  const [tags, setTags] = useState([])

  useEffect(() => {
    listTags().then(setTags).catch(() => {})
  }, [])

  const set = (key, value) => {
    const next = new URLSearchParams(params)
    if (value === '' || value == null) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const selectedTags = (params.get('tags') || '').split(',').filter(Boolean)
  const toggleTag = (name) => {
    const next = selectedTags.includes(name)
      ? selectedTags.filter((t) => t !== name)
      : [...selectedTags, name]
    set('tags', next.join(','))
  }

  return (
    <div className="filterbar">
      <select value={params.get('status') || ''} onChange={(e) => set('status', e.target.value)}>
        {STATUSES.map((s) => (
          <option key={s} value={s}>{s ? s.replace('_', ' ') : 'any status'}</option>
        ))}
      </select>
      <input
        type="number" placeholder="min $" value={params.get('min_price') || ''}
        onChange={(e) => set('min_price', e.target.value)}
      />
      <input
        type="number" placeholder="max $" value={params.get('max_price') || ''}
        onChange={(e) => set('max_price', e.target.value)}
      />
      <input
        type="number" placeholder="beds ≥" value={params.get('beds') || ''}
        onChange={(e) => set('beds', e.target.value)}
      />
      <select value={params.get('sort') || '-created_at'} onChange={(e) => set('sort', e.target.value)}>
        <option value="-created_at">newest</option>
        <option value="price">price ↑</option>
        <option value="-price">price ↓</option>
        <option value="-beds">beds ↓</option>
        <option value="-sqft">sqft ↓</option>
      </select>
      <div className="tag-filter">
        {tags.map((t) => (
          <button
            key={t.id}
            className={selectedTags.includes(t.name) ? 'tag on' : 'tag'}
            style={t.color ? { borderColor: t.color } : undefined}
            onClick={() => toggleTag(t.name)}
          >
            {t.name}
          </button>
        ))}
      </div>
    </div>
  )
}

// Turn the current URL params into the backend's query param object.
export function paramsToQuery(params) {
  const q = {}
  for (const [k, v] of params.entries()) if (v) q[k] = v
  return q
}
