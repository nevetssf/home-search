// Shared filterable columns + predicates, used by BOTH the List and Map views
// so they filter on exactly the same fields. Columns = built-in property fields
// + one per active criterion + overall score. Render is left to each view
// (the table renders cells; the map renders a filter panel).
import { useEffect, useMemo, useState } from 'react'
import { listCriteria } from './api'

// Numeric columns understand >, <, >=, <=, = prefixes; bool matches yes/no;
// everything else is a case-insensitive substring match on the displayed value.
export function matchesFilter(value, filter, type) {
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

export function compareBy(a, b, type) {
  if (a == null && b == null) return 0
  if (a == null) return 1 // nulls last
  if (b == null) return -1
  if (type === 'number') return a - b
  if (type === 'bool') return a === b ? 0 : a ? -1 : 1
  return String(a).localeCompare(String(b))
}

export function passesValueFilters(property, columns, valueFilters) {
  return columns.every((c) => matchesFilter(c.get(property), valueFilters[c.key] || '', c.type))
}

const critType = (c) =>
  c.value_type === 'boolean' ? 'bool'
  : c.value_type === 'number' || c.value_type === 'rating' ? 'number'
  : 'text'

// Loads active criteria and returns the canonical column list (key/label/type/get).
// Requires properties fetched with `with_criteria=true` for the criterion columns.
export function useFilterColumns() {
  const [criteria, setCriteria] = useState([])
  useEffect(() => { listCriteria().then(setCriteria).catch(() => {}) }, [])

  return useMemo(() => {
    const base = [
      { key: 'address', label: 'Address', type: 'text', get: (p) => p.address },
      { key: 'city', label: 'City', type: 'text', get: (p) => p.city },
      { key: 'price', label: 'Price', type: 'number', get: (p) => p.price },
      { key: 'beds', label: 'Beds', type: 'number', get: (p) => p.beds },
      { key: 'baths', label: 'Baths', type: 'number', get: (p) => p.baths },
      { key: 'sqft', label: 'Sqft', type: 'number', get: (p) => p.sqft },
      { key: 'lot_size', label: 'Lot (ac)', type: 'number', get: (p) => p.lot_size },
      { key: 'status', label: 'Status', type: 'text', get: (p) => p.status },
      { key: 'tags', label: 'Tags', type: 'text', get: (p) => (p.tags || []).map((t) => t.name).join(', ') },
    ]
    const crit = criteria.map((c) => ({
      key: `crit:${c.id}`,
      label: c.name + (c.is_subjective ? ' ★' : ''),
      type: critType(c),
      get: (p) => p.criteria?.[c.id] ?? null,
    }))
    const score = { key: 'overall_score', label: 'Score', type: 'number', get: (p) => p.overall_score }
    return [...base, ...crit, score]
  }, [criteria])
}
