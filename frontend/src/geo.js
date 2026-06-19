// Client-side point-in-shape tests, mirroring backend services/geo.py, for
// filtering the property list by drawn filter regions. Coords are [lat, lng].
const EARTH_RADIUS_MI = 3958.7613

function haversineMi([lat1, lng1], [lat2, lng2]) {
  const r = (d) => (d * Math.PI) / 180
  const dLat = r(lat2 - lat1)
  const dLng = r(lng2 - lng1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_RADIUS_MI * Math.asin(Math.sqrt(a))
}

function pointInPolygon(lat, lng, poly) {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [yi, xi] = poly[i]
    const [yj, xj] = poly[j]
    if ((xi > lng) !== (xj > lng)) {
      const at = ((yj - yi) * (lng - xi)) / ((xj - xi) || 1e-12) + yi
      if (lat < at) inside = !inside
    }
  }
  return inside
}

export function contains(shape, lat, lng) {
  if (lat == null || lng == null) return false
  if (shape.kind === 'rectangle' && shape.bbox) {
    const [minLat, minLng, maxLat, maxLng] = shape.bbox
    return lat >= minLat && lat <= maxLat && lng >= minLng && lng <= maxLng
  }
  if (shape.kind === 'circle' && shape.center && shape.radius_mi != null) {
    return haversineMi(shape.center, [lat, lng]) <= shape.radius_mi
  }
  if (shape.kind === 'polygon' && shape.points?.length >= 3) {
    return pointInPolygon(lat, lng, shape.points)
  }
  return false
}

export const inAnyShape = (shapes, lat, lng) =>
  shapes.some((s) => contains(s, lat, lng))
