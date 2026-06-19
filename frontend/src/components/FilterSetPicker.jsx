// Dropdown to select the active filter set, plus new / rename / delete.
// Shared by the List and Map views (both filter on the active set).
import { useFilterSets } from '../filterSets'

export default function FilterSetPicker() {
  const { sets, activeId, active, selectSet, createSet, renameSet, deleteSet } = useFilterSets()

  const onNew = async () => {
    const name = prompt('New filter set name:')
    if (!name) return
    try { await createSet(name.trim()) } catch { alert('A filter set with that name already exists.') }
  }
  const onRename = async () => {
    const name = prompt('Rename filter set to:', active?.name || '')
    if (!name) return
    try { await renameSet(name.trim()) } catch { alert('A filter set with that name already exists.') }
  }
  const onDelete = () => {
    if (active && confirm(`Delete filter set “${active.name}”?`)) deleteSet()
  }

  return (
    <span className="filterset-picker">
      <label className="muted">Filter set:</label>
      <select value={activeId ?? ''} onChange={(e) => selectSet(e.target.value)}>
        {sets.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
      <button className="link-btn" onClick={onNew}>+ new</button>
      <button className="link-btn" onClick={onRename} disabled={!active}>rename</button>
      <button className="link-btn danger" onClick={onDelete} disabled={!active}>delete</button>
    </span>
  )
}
