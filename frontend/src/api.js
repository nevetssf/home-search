// Typed-ish fetch client. baseURL is the Vite proxy in dev (/api) or VITE_API_URL
// in prod. The JWT is attached from localStorage on every request.
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && !location.pathname.startsWith('/login')) {
      localStorage.removeItem('token')
      location.href = '/login'
    }
    return Promise.reject(err)
  }
)

// ── Auth ────────────────────────────────────────────────────────────────────
export const login = (email, password) =>
  api.post('/auth/login', { email, password }).then((r) => r.data)
export const getMe = () => api.get('/auth/me').then((r) => r.data)
export const listUsers = () => api.get('/auth/users').then((r) => r.data)
export const createUser = (body) => api.post('/auth/users', body).then((r) => r.data)
export const deleteUser = (id) => api.delete(`/auth/users/${id}`)
export const changePassword = (current_password, new_password) =>
  api.patch('/auth/me/password', { current_password, new_password })

// ── Properties ────────────────────────────────────────────────────────────────
// The List and Map filter/plot everything client-side, so load all properties
// (default limit high; callers can still override).
export const listProperties = (params = {}) =>
  api.get('/properties', { params: { limit: 20000, ...params } }).then((r) => r.data)
export const getProperty = (id) => api.get(`/properties/${id}`).then((r) => r.data)
export const createProperty = (body) =>
  api.post('/properties', body).then((r) => r.data)
export const updateProperty = (id, body) =>
  api.patch(`/properties/${id}`, body).then((r) => r.data)
export const deleteProperty = (id) => api.delete(`/properties/${id}`)
export const setPropertyTags = (id, tagIds) =>
  api.put(`/properties/${id}/tags`, tagIds).then((r) => r.data)
export const addNote = (id, body) =>
  api.post(`/properties/${id}/notes`, { body }).then((r) => r.data)
export const listNotes = (id) =>
  api.get(`/properties/${id}/notes`).then((r) => r.data)
export const updateNote = (id, noteId, body) =>
  api.patch(`/properties/${id}/notes/${noteId}`, { body }).then((r) => r.data)
export const deleteNote = (id, noteId) =>
  api.delete(`/properties/${id}/notes/${noteId}`)

// ── Tags ──────────────────────────────────────────────────────────────────────
export const listTags = () => api.get('/tags').then((r) => r.data)
export const createTag = (body) => api.post('/tags', body).then((r) => r.data)

// ── Criteria ──────────────────────────────────────────────────────────────────
export const listCriteria = (includeInactive = false) =>
  api.get('/criteria', { params: { include_inactive: includeInactive } }).then((r) => r.data)
export const createCriterion = (body) =>
  api.post('/criteria', body).then((r) => r.data)
export const updateCriterion = (id, body) =>
  api.patch(`/criteria/${id}`, body).then((r) => r.data)
export const deleteCriterion = (id) => api.delete(`/criteria/${id}`)
export const getPropertyCriteria = (id) =>
  api.get(`/properties/${id}/criteria`).then((r) => r.data)
export const setCriterionValue = (propertyId, criterionId, body) =>
  api.put(`/properties/${propertyId}/criteria/${criterionId}`, body).then((r) => r.data)

// ── Media ─────────────────────────────────────────────────────────────────────
export const listMedia = (propertyId) =>
  api.get('/media', { params: { property_id: propertyId } }).then((r) => r.data)
export const uploadMedia = (propertyId, file, caption) => {
  const fd = new FormData()
  fd.append('property_id', propertyId)
  fd.append('file', file)
  if (caption) fd.append('caption', caption)
  return api.post('/media', fd).then((r) => r.data)
}
// Media files require the auth header, so fetch as a blob and make an object URL.
export const mediaBlobUrl = async (mediaId) => {
  const r = await api.get(`/media/${mediaId}/file`, { responseType: 'blob' })
  return URL.createObjectURL(r.data)
}

// ── Distances & POIs ────────────────────────────────────────────────────────────
export const getDistances = (id) =>
  api.get(`/properties/${id}/distances`).then((r) => r.data)
export const refreshDistances = (id) =>
  api.post(`/properties/${id}/distances/refresh`).then((r) => r.data)
export const listPois = () => api.get('/pois').then((r) => r.data)
export const createPoi = (body) => api.post('/pois', body).then((r) => r.data)

// ── Ingestion ──────────────────────────────────────────────────────────────────
// Unified: backend detects Zillow vs Redfin and scrapes the page directly
// (RapidAPI fallback for Zillow if a key is set).
export const ingestUrl = (url) =>
  api.post('/ingest/url', { url }).then((r) => r.data)
export const ingestRedfinCsv = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/ingest/redfin/csv', fd).then((r) => r.data)
}
// Area/criteria search on Realtor.com (HomeHarvest, no API key); pass any
// subset of {location, listing_type, radius, beds_min, price_min, price_max}.
export const ingestRealtorSearch = (params) =>
  api.post('/ingest/realtor/search', params).then((r) => r.data)
// Search the listing source within map-drawn region(s). shapes: [{kind, ...}].
export const searchRegion = (shapes, opts = {}) =>
  api.post('/ingest/region', { shapes, ...opts }).then((r) => r.data)
// "Update": find new listings in the search regions + refresh existing statuses.
export const refreshListings = (searchRegions = [], criteria = {}) =>
  api.post('/ingest/refresh', { search_regions: searchRegions, refresh_existing: true, ...criteria }).then((r) => r.data)

// Streaming variant: calls onEvent(evt) for each NDJSON progress event
// (start / city / error / done). Uses fetch since axios can't stream in-browser.
// Returns the final "done" event.
export async function refreshListingsStream(searchRegions = [], criteria = {}, onEvent = () => {}) {
  const token = localStorage.getItem('token')
  const base = import.meta.env.VITE_API_URL || '/api'
  const resp = await fetch(`${base}/ingest/refresh/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ search_regions: searchRegions, refresh_existing: true, ...criteria }),
  })
  if (!resp.ok) {
    const err = new Error('refresh failed')
    err.response = { status: resp.status }
    throw err
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let done = null
  for (;;) {
    const { done: finished, value } = await reader.read()
    if (finished) break
    buf += decoder.decode(value, { stream: true })
    let nl
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (!line) continue
      const evt = JSON.parse(line)
      onEvent(evt)
      if (evt.event === 'done') done = evt
    }
  }
  return done
}

// ── Filter sets (named, persisted filter criteria) ────────────────────────────
export const listFilterSets = () => api.get('/filter-sets').then((r) => r.data)
export const createFilterSet = (body) => api.post('/filter-sets', body).then((r) => r.data)
export const updateFilterSet = (id, body) =>
  api.patch(`/filter-sets/${id}`, body).then((r) => r.data)
export const deleteFilterSet = (id) => api.delete(`/filter-sets/${id}`)

export default api
