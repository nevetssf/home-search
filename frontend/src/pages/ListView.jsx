import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { listProperties } from '../api'
import FilterBar, { paramsToQuery } from '../components/FilterBar'
import AddPropertyBar from '../components/AddPropertyBar'

const fmtPrice = (p) => (p == null ? '—' : `$${Number(p).toLocaleString()}`)

export default function ListView() {
  const [params] = useSearchParams()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    listProperties(paramsToQuery(params))
      .then(setRows)
      .finally(() => setLoading(false))
  }

  useEffect(load, [params])

  return (
    <div>
      <AddPropertyBar onChange={load} />
      <FilterBar />
      {loading ? (
        <p>Loading…</p>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>Address</th><th>City</th><th>Price</th><th>Beds</th>
              <th>Baths</th><th>Sqft</th><th>Status</th><th>Tags</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td><Link to={`/property/${p.id}`}>{p.address || `#${p.id}`}</Link></td>
                <td>{p.city}</td>
                <td>{fmtPrice(p.price)}</td>
                <td>{p.beds ?? '—'}</td>
                <td>{p.baths ?? '—'}</td>
                <td>{p.sqft ?? '—'}</td>
                <td><span className={`badge ${p.status}`}>{p.status?.replace('_', ' ')}</span></td>
                <td>{p.tags?.map((t) => <span key={t.id} className="tag sm">{t.name}</span>)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={8} className="muted">No properties match.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
