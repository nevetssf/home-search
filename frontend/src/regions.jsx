// Lightweight, localStorage-persisted UI/session state shared by List & Map:
//   • search   — region shapes that "Search this area" pulls listings from
//   • sort     — list sort {key, dir}
//   • listFade / mapFade — per-view: true = fade non-matches, false = hide them
// (Filter *criteria* — value filters + filter regions — live in named filter
// sets persisted server-side; see filterSets.jsx.)
import { createContext, useContext, useEffect, useState } from 'react'

const KEY = 'home-search:viewstate'
const Ctx = createContext(null)

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {}
  } catch {
    return {}
  }
}

export function RegionsProvider({ children }) {
  const init = load()
  const [search, setSearch] = useState(init.search || [])
  const [sort, setSort] = useState(init.sort || { key: 'created', dir: 1 })
  const [listFade, setListFade] = useState(init.listFade ?? true)
  const [mapFade, setMapFade] = useState(init.mapFade ?? true)

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify({ search, sort, listFade, mapFade }))
  }, [search, sort, listFade, mapFade])

  return (
    <Ctx.Provider
      value={{
        search, setSearch,
        sort, setSort,
        listFade, setListFade,
        mapFade, setMapFade,
      }}
    >
      {children}
    </Ctx.Provider>
  )
}

export const useViewState = () => useContext(Ctx)
