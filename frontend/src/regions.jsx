// Shared store for map-drawn regions, in two sets:
//   • search — regions to pull listings from (drives POST /ingest/region)
//   • filter — regions that narrow which properties show in the List view
// Lives above the routes (so it survives List↔Map navigation) and is persisted
// to localStorage (so it survives reloads). Each set is an array of shape
// payloads: { kind:'rectangle'|'circle'|'polygon', ... } with [lat,lng] coords.
import { createContext, useContext, useEffect, useState } from 'react'

const KEY = 'home-search:regions'
const RegionsContext = createContext(null)

function load() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY))
    return { search: v?.search || [], filter: v?.filter || [] }
  } catch {
    return { search: [], filter: [] }
  }
}

export function RegionsProvider({ children }) {
  const initial = load()
  const [search, setSearch] = useState(initial.search)
  const [filter, setFilter] = useState(initial.filter)

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify({ search, filter }))
  }, [search, filter])

  return (
    <RegionsContext.Provider value={{ search, setSearch, filter, setFilter }}>
      {children}
    </RegionsContext.Provider>
  )
}

export const useRegions = () => useContext(RegionsContext)
