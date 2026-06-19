// Named filter sets, persisted server-side (/filter-sets). Each set's payload
// holds the filter criteria { value_filters, filter_regions }. The active set
// drives filtering in both the List and Map views; edits auto-save (debounced).
// The active selection is remembered in localStorage so the same set reopens.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import * as api from './api'

const ACTIVE_KEY = 'home-search:activeFilterSet'
const Ctx = createContext(null)
const emptyPayload = () => ({ value_filters: {}, filter_regions: [] })

export function FilterSetsProvider({ children }) {
  const [sets, setSets] = useState([])
  const [activeId, setActiveId] = useState(() => {
    const v = localStorage.getItem(ACTIVE_KEY)
    return v ? Number(v) : null
  })
  const saveTimer = useRef()

  // Load sets on mount; ensure at least one exists ("Default").
  useEffect(() => {
    let alive = true
    api.listFilterSets()
      .then(async (list) => {
        if (!alive) return
        if (list.length === 0) {
          const def = await api.createFilterSet({ name: 'Default', payload: emptyPayload() })
          if (alive) { setSets([def]); setActiveId(def.id) }
        } else {
          setSets(list)
          setActiveId((prev) => (prev && list.some((s) => s.id === prev) ? prev : list[0].id))
        }
      })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (activeId != null) localStorage.setItem(ACTIVE_KEY, String(activeId))
  }, [activeId])

  const active = sets.find((s) => s.id === activeId) || null
  const valueFilters = active?.payload?.value_filters || {}
  const filterRegions = active?.payload?.filter_regions || []

  const scheduleSave = (id, payload) => {
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => { api.updateFilterSet(id, { payload }).catch(() => {}) }, 500)
  }

  const patchPayload = useCallback((patch) => {
    setSets((cur) => cur.map((s) => {
      if (s.id !== activeId) return s
      const payload = { ...emptyPayload(), ...s.payload, ...patch }
      scheduleSave(s.id, payload)
      return { ...s, payload }
    }))
  }, [activeId])

  const setValueFilters = useCallback((v) => {
    patchPayload({ value_filters: typeof v === 'function' ? v(valueFilters) : v })
  }, [patchPayload, valueFilters])
  const setFilterRegions = useCallback((v) => {
    patchPayload({ filter_regions: typeof v === 'function' ? v(filterRegions) : v })
  }, [patchPayload, filterRegions])

  const selectSet = (id) => setActiveId(Number(id))

  const createSet = async (name) => {
    const ns = await api.createFilterSet({ name, payload: emptyPayload() })
    setSets((c) => [...c, ns])
    setActiveId(ns.id)
    return ns
  }
  const renameSet = async (name) => {
    if (!active) return
    const up = await api.updateFilterSet(active.id, { name })
    setSets((c) => c.map((s) => (s.id === up.id ? up : s)))
  }
  const deleteSet = async () => {
    if (!active) return
    await api.deleteFilterSet(active.id)
    const rest = sets.filter((s) => s.id !== active.id)
    if (rest.length) {
      setSets(rest)
      setActiveId(rest[0].id)
    } else {
      const def = await api.createFilterSet({ name: 'Default', payload: emptyPayload() })
      setSets([def])
      setActiveId(def.id)
    }
  }

  return (
    <Ctx.Provider
      value={{
        sets, active, activeId,
        valueFilters, setValueFilters,
        filterRegions, setFilterRegions,
        selectSet, createSet, renameSet, deleteSet,
      }}
    >
      {children}
    </Ctx.Provider>
  )
}

export const useFilterSets = () => useContext(Ctx)
