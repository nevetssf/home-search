import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { deleteProperty, listProperties } from '../api'
import AddPropertyBar from '../components/AddPropertyBar'
import FilterSetPicker from '../components/FilterSetPicker'
import { useViewState } from '../regions'
import { useFilterSets } from '../filterSets'
import { compareBy, passesValueFilters, useFilterColumns } from '../filters'
import { inAnyShape } from '../geo'

const fmtPrice = (p) => (p == null ? '—' : `$${Number(p).toLocaleString()}`)

// View-specific cell rendering for the shared columns.
function renderCell(col, p) {
  const v = col.get(p)
  if (col.key === 'address') return (
    <span className="addr-cell">
      {p.source_url && (
        <a
          href={p.source_url} target="_blank" rel="noreferrer"
          title="Open listing in a new tab"
          onClick={(e) => e.stopPropagation()}
        >↗</a>
      )}
      <Link to={`/property/${p.id}`}>{v || `#${p.id}`}</Link>
    </span>
  )
  if (col.key === 'price') return fmtPrice(v)
  if (col.key === 'status') return <span className={`badge ${v}`}>{v?.replace('_', ' ')}</span>
  if (col.key === 'tags') return v ? v.split(', ').map((n) => <span key={n} className="tag sm">{n}</span>) : ''
  if (col.key === 'overall_score') return v == null ? '—' : `${Math.round(v * 100)}%`
  if (col.type === 'bool') return v == null ? '—' : v ? '✓' : '✗'
  return v ?? '—'
}

export default function ListView() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const { sort, setSort, listFade, setListFade } = useViewState()
  const {
    valueFilters, setValueFilters, filterRegions, setFilterRegions,
  } = useFilterSets()
  const columns = useFilterColumns()

  const load = () => {
    setLoading(true)
    listProperties({ with_criteria: true })
      .then(setRows)
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const remove = async (p, e) => {
    e.preventDefault(); e.stopPropagation()
    if (!confirm(`Delete ${p.address || `property #${p.id}`} permanently? This cannot be undone.`)) return
    await deleteProperty(p.id)
    load()
  }

  // A property "matches" if it passes the value filters AND the spatial filter
  // regions (if any). Non-matches are faded or hidden per fadeMode.
  const passes = useMemo(() => {
    return (p) =>
      passesValueFilters(p, columns, valueFilters) &&
      (filterRegions.length === 0 || inAnyShape(filterRegions, p.latitude, p.longitude))
  }, [columns, valueFilters, filterRegions])

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sort.key)
    if (!col) return rows
    return [...rows].sort((a, b) => sort.dir * compareBy(col.get(a), col.get(b), col.type))
  }, [rows, columns, sort])

  const visible = listFade ? sorted : sorted.filter(passes)
  const matchCount = useMemo(() => rows.filter(passes).length, [rows, passes])
  const filtersActive = Object.values(valueFilters).some(Boolean) || filterRegions.length > 0

  const toggleSort = (key) =>
    setSort(sort.key === key ? { key, dir: -sort.dir } : { key, dir: 1 })
  const setFilter = (key, val) => setValueFilters({ ...valueFilters, [key]: val })

  return (
    <div className="listview">
      <AddPropertyBar onChange={load} />
      <div className="list-toolbar">
        <FilterSetPicker />
        <span className="muted">
          {filtersActive ? `${matchCount} of ${rows.length} match` : `${rows.length} properties`}
        </span>
        <label className="inline-check">
          <input type="checkbox" checked={listFade} onChange={(e) => setListFade(e.target.checked)} />
          fade non-matches (uncheck to hide)
        </label>
        {filtersActive && (
          <button className="link-btn" onClick={() => { setValueFilters({}); setFilterRegions([]) }}>
            clear all filters
          </button>
        )}
      </div>
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
                      value={valueFilters[c.key] || ''}
                      placeholder={c.type === 'number' ? '>0' : 'filter'}
                      onChange={(e) => setFilter(c.key, e.target.value)}
                    />
                  </th>
                ))}
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((p) => (
                <tr key={p.id} className={passes(p) ? '' : 'faded'}>
                  {columns.map((c) => (
                    <td key={c.key}>{renderCell(c, p)}</td>
                  ))}
                  <td><button className="link-btn danger" onClick={(e) => remove(p, e)}>delete</button></td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr><td colSpan={columns.length + 1} className="muted">No properties match.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
