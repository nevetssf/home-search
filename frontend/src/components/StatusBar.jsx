// Fixed status bar at the bottom of the screen. Driven by the shared `status`
// in the view store — long searches update it per city so you can see progress.
import { useViewState } from '../regions'

export default function StatusBar() {
  const { status, setStatus } = useViewState()
  if (!status) return null

  const pct = status.total ? Math.round(((status.index || 0) / status.total) * 100) : 0
  const t = status.totals

  return (
    <div className={`statusbar ${status.active ? 'active' : 'done'}`}>
      {status.active && <span className="statusbar-spinner" />}
      <span className="statusbar-text">{status.text}</span>
      {status.total ? (
        <div className="statusbar-track"><div className="statusbar-fill" style={{ width: `${pct}%` }} /></div>
      ) : null}
      {t && (
        <span className="muted">
          {t.created} new · {t.updated} updated{t.status_changed ? ` · ${t.status_changed} status` : ''}
        </span>
      )}
      {status.errors > 0 && (
        <span className="statusbar-errors" title="Some city searches failed (possible rate-limiting/block)">
          ⚠ {status.errors} failed
        </span>
      )}
      {!status.active && (
        <button className="link-btn" onClick={() => setStatus(null)}>✕</button>
      )}
    </div>
  )
}
