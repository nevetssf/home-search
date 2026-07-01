// Runs the streaming refresh and drives the bottom status bar with per-city
// progress. Shared by the Search pop-up and the list's Update button so both
// give the same live feedback for long searches.
import { refreshListingsStream } from './api'

export async function runRefreshWithStatus(regions, criteria, { setStatus, bumpData }) {
  let errors = 0
  setStatus({ active: true, text: 'Starting search…', total: 0 })
  try {
    const done = await refreshListingsStream(regions, criteria, (evt) => {
      if (evt.event === 'start') {
        setStatus({
          active: true, text: `Searching ${evt.cities} area${evt.cities === 1 ? '' : 's'}…`,
          index: 0, total: evt.total, totals: { created: 0, updated: 0, status_changed: 0 }, errors,
        })
      } else if (evt.event === 'city') {
        setStatus({
          active: true, text: `Searched ${evt.city}`,
          index: evt.index, total: evt.total, totals: evt.totals, errors,
        })
      } else if (evt.event === 'error') {
        errors += 1
      }
    })
    setStatus({
      active: false,
      text: `Done: ${done.created} new, ${done.updated} updated${done.status_changed ? `, ${done.status_changed} status changes` : ''}.`,
      totals: { created: done.created, updated: done.updated, status_changed: done.status_changed },
      errors: (done.errors || []).length,
    })
    bumpData()
    return done
  } catch (e) {
    setStatus({
      active: false,
      text: e.response?.status === 503 ? 'Search unavailable (no sources enabled).' : 'Search failed.',
      errors,
    })
    throw e
  }
}
