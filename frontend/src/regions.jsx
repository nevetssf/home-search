// Lightweight, localStorage-persisted UI/session state shared by List & Map:
//   • search   — region shapes that "Search this area" pulls listings from
//   • sort     — list sort {key, dir}
//   • listFade / mapFade — per-view: true = fade non-matches, false = hide them
//   • searchCriteria — shared search params (price/beds/…) for region/Update searches
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
  const [searchCriteria, setSearchCriteria] = useState(init.searchCriteria || {})
  const [dataVersion, setDataVersion] = useState(0)  // bump to make views reload
  const [status, setStatus] = useState(null)  // bottom status bar: {active,text,...}

  useEffect(() => {
    localStorage.setItem(
      KEY, JSON.stringify({ search, sort, listFade, mapFade, searchCriteria })
    )
  }, [search, sort, listFade, mapFade, searchCriteria])

  return (
    <Ctx.Provider
      value={{
        search, setSearch,
        sort, setSort,
        listFade, setListFade,
        mapFade, setMapFade,
        searchCriteria, setSearchCriteria,
        dataVersion, bumpData: () => setDataVersion((v) => v + 1),
        status, setStatus,
      }}
    >
      {children}
    </Ctx.Provider>
  )
}

export const useViewState = () => useContext(Ctx)
