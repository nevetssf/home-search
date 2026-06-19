import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { deleteProperty, listCriteria, listProperties } from '../api'
import FilterBar, { paramsToQuery } from '../components/FilterBar'
import AddPropertyBar from '../components/AddPropertyBar'

const fmtPrice = (p) => (p == null ? '—' : `$${Number(p).toLocaleString()}`)

// ── client-side sort/filter helpers (applied over the ~50 loaded rows) ────────
function compare(a, b, type) {
  if (a == null && b == null) return 0
  if (a == null) return 1 // nulls last
  if (b == null) return -1
  if (type === 'number') return a - b
  if (type === 'bool') return a === b ? 0 : a ? -1 : 1
  return String(a).localeCompare(String(b))
}

// Numeric columns understand >, <, >=, <=, = prefixes; everything else is a
// case-insensitive substring match on the displayed value.
function matches(value, filter, type) {
  if (!filter) return true
  if (type === 'number') {
    const m = filter.match(/^\s*(>=|<=|>|<|=)?\s*(-?\d+\.?\d*)\s*$/)
    if (m) {
      if (value == null) return false
      const n = parseFloat(m[2])
      switch (m[1]) {
        case '>': return value > n
        case '<': return value < n
        case '>=': return value >= n
        case '<=': return value <= n
        case '=': return value === n
        default: return value === n
      }
    }
  }
  if (type === 'bool') {
    if (value == null) return false
    return (value ? 'yes' : 'no').includes(filter.toLowerCase())
  }
  return String(value ?? '').toLowerCase().includes(filter.toLowerCase())
}

export default function ListView() {
  const [params] = useSearchParams()
  const [rows, setRows] = useState([])
  const [criteria, setCriteria] = useState([])
  const [loading, setLoading] = useState(true)
  const [sort, setSort] = useState({ key: 'created', dir: 1 })
  const [colFilters, setColFilters] = useState({}) // {colKey: text}

  const load = () => {
    setLoading(true)
    Promise.all([
      listProperties({ ...paramsToQuery(params), with_criteria: true }),
      listCriteria(),
    ])
      .then(([props, crits]) => { setRows(props); setCriteria(crits) })
      .finally(() => setLoading(false))
  }

  useEffect(load, [params])

  const remove = async (p, e) => {
    e.preventDefault(); e.stopPropagation()
    if (!confirm(`Delete ${p.address || `property #${p.id}`} permanently? This cannot be undone.`)) return
    await deleteProperty(p.id)
    load()
  }

  // Columns: built-ins + one per criterion + overall score.
  const columns = useMemo(() => {
    const critType = (c) =>
      c.value_type === 'boolean' ? 'bool'
      : c.value_type === 'number' || c.value_type === 'rating' ? 'number'
      : 'text'
    const base = [
      { key: 'address', label: 'Address', type: 'text', get: (p) => p.address,
        render: (v, p) => <Link to={`/property/${p.id}`}>{v || `#${p.id}`}</Link> },
      { key: 'city', label: 'City', type: 'text', get: (p) => p.city },
      { key: 'price', label: 'Price', type: 'number', get: (p) => p.price, render: fmtPrice },
      { key: 'beds', label: 'Beds', type: 'number', get: (p) => p.beds },
      { key: 'baths', label: 'Baths', type: 'number', get: (p) => p.baths },
      { key: 'sqft', label: 'Sqft', type: 'number', get: (p) => p.sqft },
      { key: 'lot_size', label: 'Lot (ac)', type: 'number', get: (p) => p.lot_size },
      { key: 'status', label: 'Status', type: 'text', get: (p) => p.status,
        render: (v) => <span className={`badge ${v}`}>{v?.replace('_', ' ')}</span> },
      { key: 'tags', label: 'Tags', type: 'text',
        get: (p) => (p.tags || []).map((t) => t.name).join(', '),
        render: (v) => v ? v.split(', ').map((n) => <span key={n} className="tag sm">{n}</span>) : '' },
    ]
    const crit = criteria.map((c) => {
      const type = critType(c)
      return {
        key: `crit:${c.id}`, label: c.name + (c.is_subjective ? ' ★' : ''), type,
        get: (p) => p.criteria?.[c.id] ?? null,
        render: (v) =>
          v == null ? '—'
          : type === 'bool' ? (v ? '✓' : '✗')
          : v,
      }
    })
    const score = {
      key: 'overall_score', label: 'Score', type: 'number',
      get: (p) => p.overall_score,
      render: (v) => (v == null ? '—' : `${Math.round(v * 100)}%`),
    }
    return [...base, ...crit, score]
  }, [criteria])

  const view = useMemo(() => {
    let out = rows.filter((p) =>
      columns.every((c) => matches(c.get(p), colFilters[c.key] || '', c.type))
    )
    const col = columns.find((c) => c.key === sort.key)
    if (col) out = [...out].sort((a, b) => sort.dir * compare(col.get(a), col.get(b), col.type))
    return out
  }, [rows, columns, colFilters, sort])

  const toggleSort = (key) =>
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))

  const setFilter = (key, val) => setColFilters((f) => ({ ...f, [key]: val }))

  return (
    <div>
      <AddPropertyBar onChange={load} />
      <FilterBar />
      {loading ? (
        <p>Loading…</p>
      ) : (
        <div className="table-scroll">
          <table className="grid">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key} className="sortable" onClick={() => toggleSort(c.key)}>
                    {c.label}{sort.key === c.key ? (sort.dir > 0 ? ' ▲' : ' ▼') : ''}
                  </th>
                ))}
                <th />
              </tr>
              <tr className="filter-row">
                {columns.map((c) => (
                  <th key={c.key}>
                    <input
                      value={colFilters[c.key] || ''}
                      placeholder={c.type === 'number' ? '>0' : 'filter'}
                      onChange={(e) => setFilter(c.key, e.target.value)}
                    />
                  </th>
                ))}
                <th />
              </tr>
            </thead>
            <tbody>
              {view.map((p) => (
                <tr key={p.id}>
                  {columns.map((c) => (
                    <td key={c.key}>{c.render ? c.render(c.get(p), p) : (c.get(p) ?? '—')}</td>
                  ))}
                  <td><button className="link-btn danger" onClick={(e) => remove(p, e)}>delete</button></td>
                </tr>
              ))}
              {view.length === 0 && (
                <tr><td colSpan={columns.length + 1} className="muted">No properties match.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
