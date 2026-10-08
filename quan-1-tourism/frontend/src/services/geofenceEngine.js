const EARTH_RADIUS_METERS = 6371000;

function distanceMeters(a, b) {
  const radians = Math.PI / 180;
  const dLat = (b[1] - a[1]) * radians;
  const dLng = (b[0] - a[0]) * radians;
  const lat1 = a[1] * radians;
  const lat2 = b[1] * radians;
  const value = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return EARTH_RADIUS_METERS * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

export class GeofenceEngine {
  constructor(pois, onEnterPoi, onExitPoi = () => {}) {
    this.pois = pois;
    this.onEnterPoi = onEnterPoi;
    this.onExitPoi = onExitPoi;
    this.activeZones = new Set();
    this.cooldowns = new Map();
    this.entryCandidates = new Map();
    this.lastCheckAt = 0;
  }

  checkPosition(coords) {
    const now = Date.now();
    if (now - this.lastCheckAt < 3000) return;
    this.lastCheckAt = now;
    const userPoint = [coords.longitude, coords.latitude];
    const candidates = this.pois.map((poi) => ({ poi, distance: distanceMeters(userPoint, poi.location.coordinates) }))
      .filter(({ poi, distance }) => distance <= (poi.geofence_radius || 30))
      .sort((a, b) => a.distance - b.distance);
    const nearest = candidates[0]?.poi;

    for (const poi of this.pois) {
      if (poi.id !== nearest?.id && this.activeZones.has(poi.id)) {
        this.activeZones.delete(poi.id);
        this.cooldowns.set(poi.id, now);
        this.onExitPoi(poi);
      }
    }
    if (nearest && !this.activeZones.has(nearest.id) && now - (this.cooldowns.get(nearest.id) || 0) >= 5 * 60 * 1000) {
      const enteredAt = this.entryCandidates.get(nearest.id);
      if (enteredAt == null) this.entryCandidates.set(nearest.id, now);
      else if (now - enteredAt >= 3000) {
        this.entryCandidates.delete(nearest.id);
        this.activeZones.add(nearest.id);
        this.onEnterPoi(nearest);
      }
    } else if (nearest) {
      this.entryCandidates.delete(nearest.id);
    }
    if (!nearest) {
      this.entryCandidates.clear();
    }
  }
}
