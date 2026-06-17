// Media gallery: promo photos (cached locally) + user uploads. Files are
// auth-gated, so each is fetched as a blob and shown via an object URL.
import { useEffect, useState } from 'react'
import { listMedia, mediaBlobUrl, uploadMedia } from '../api'

function Thumb({ media }) {
  const [src, setSrc] = useState(null)
  useEffect(() => {
    let url
    mediaBlobUrl(media.id).then((u) => { url = u; setSrc(u) }).catch(() => {})
    return () => url && URL.revokeObjectURL(url)
  }, [media.id])
  if (media.kind !== 'photo') {
    return <div className="thumb doc">{media.kind}</div>
  }
  return src ? <img className="thumb" src={src} alt={media.caption || ''} /> : <div className="thumb loading" />
}

export default function MediaGallery({ propertyId }) {
  const [media, setMedia] = useState([])
  const [busy, setBusy] = useState(false)

  const load = () => listMedia(propertyId).then(setMedia)
  useEffect(() => { load() }, [propertyId])

  const onUpload = async (e) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    setBusy(true)
    try {
      for (const f of files) await uploadMedia(propertyId, f)
      await load()
    } finally {
      setBusy(false)
      e.target.value = ''
    }
  }

  const promo = media.filter((m) => m.origin === 'promo')
  const uploads = media.filter((m) => m.origin === 'upload')

  return (
    <div className="gallery">
      {promo.length > 0 && (
        <>
          <h4>Listing photos</h4>
          <div className="thumbs">{promo.map((m) => <Thumb key={m.id} media={m} />)}</div>
        </>
      )}
      <h4>My uploads
        <label className="filelabel inline">
          {busy ? 'Uploading…' : '+ add'}
          <input type="file" hidden multiple onChange={onUpload} disabled={busy} />
        </label>
      </h4>
      <div className="thumbs">
        {uploads.map((m) => <Thumb key={m.id} media={m} />)}
        {uploads.length === 0 && <span className="muted">No uploads yet.</span>}
      </div>
    </div>
  )
}
