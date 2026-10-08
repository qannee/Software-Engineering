const MAP_VERSION = import.meta.env.VITE_MAP_VERSION || '1';
export const OFFLINE_MAP_CACHE = `q1-tourism-map-v${MAP_VERSION}`;
export const MAP_TILE_URL = import.meta.env.VITE_MAP_TILE_URL || '';
export const MAP_ATTRIBUTION = import.meta.env.VITE_MAP_ATTRIBUTION || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export function tileUrl(template, z, x, y) {
  const subdomains = (import.meta.env.VITE_MAP_SUBDOMAINS || 'abc').split('');
  const subdomain = subdomains[Math.abs(x + y) % subdomains.length] || '';
  return template
    .replaceAll('{z}', String(z))
    .replaceAll('{x}', String(x))
    .replaceAll('{y}', String(y))
    .replaceAll('{-y}', String((2 ** z) - 1 - y))
    .replaceAll('{s}', subdomain);
}

function longitudeTile(longitude, zoom) {
  return Math.floor(((longitude + 180) / 360) * (2 ** zoom));
}

function latitudeTile(latitude, zoom) {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, latitude));
  const radians = clamped * Math.PI / 180;
  return Math.floor((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2 * (2 ** zoom));
}

export function listDistrictTiles(pois, minZoom = 12, maxZoom = 16) {
  if (!MAP_TILE_URL || !pois.length) return [];
  const coordinates = pois.map((poi) => poi.location.coordinates);
  const padding = 0.008;
  const west = Math.min(...coordinates.map(([longitude]) => longitude)) - padding;
  const east = Math.max(...coordinates.map(([longitude]) => longitude)) + padding;
  const south = Math.min(...coordinates.map(([, latitude]) => latitude)) - padding;
  const north = Math.max(...coordinates.map(([, latitude]) => latitude)) + padding;
  const tiles = [];
  for (let z = minZoom; z <= maxZoom; z += 1) {
    const minX = longitudeTile(west, z), maxX = longitudeTile(east, z);
    const minY = latitudeTile(north, z), maxY = latitudeTile(south, z);
    for (let x = minX; x <= maxX; x += 1) {
      for (let y = minY; y <= maxY; y += 1) tiles.push({ z, x, y, url: tileUrl(MAP_TILE_URL, z, x, y) });
    }
  }
  if (tiles.length > 2000) throw new Error('Gói bản đồ vượt quá 2.000 ô; hãy thu hẹp vùng hoặc mức phóng.');
  return tiles;
}

export async function cacheDistrictTiles(pois, onProgress = () => {}) {
  const tiles = listDistrictTiles(pois);
  if (!tiles.length) return { count: 0, bytes: 0 };
  let cache = await caches.open(OFFLINE_MAP_CACHE);
  const manifestUrl = new URL('/offline-map-manifest.json', window.location.origin).href;
  const previousManifest = await cache.match(manifestUrl);
  if (previousManifest) {
    const previous = await previousManifest.json();
    if (previous.tile_template !== MAP_TILE_URL) {
      await caches.delete(OFFLINE_MAP_CACHE);
      cache = await caches.open(OFFLINE_MAP_CACHE);
    }
  }
  const estimate = await Promise.resolve(navigator.storage?.estimate?.()).catch(() => null);
  const freeBytes = estimate?.quota && estimate?.usage != null
    ? Math.max(0, estimate.quota - estimate.usage - 12 * 1024 * 1024)
    : 96 * 1024 * 1024;
  const byteLimit = Math.min(128 * 1024 * 1024, freeBytes);
  if (byteLimit < 4 * 1024 * 1024) throw new Error('Thiết bị gần hết dung lượng trống để lưu bản đồ.');

  let completed = 0;
  let bytes = 0;
  let cursor = 0;
  const worker = async () => {
    while (cursor < tiles.length) {
      const tile = tiles[cursor++];
      const key = new Request(tile.url, { mode: 'cors' });
      if (!await cache.match(key)) {
        const response = await fetch(key);
        if (!response.ok || response.type === 'opaque') throw new Error(`Không tải được ô bản đồ (${response.status}). Kiểm tra CORS của nhà cung cấp.`);
        const copy = response.clone();
        const blob = await copy.blob();
        bytes += blob.size;
        if (bytes > byteLimit) throw new Error('Gói bản đồ vượt dung lượng trống cho phép. Đã giữ các ô đã tải để có thể tiếp tục.');
        await cache.put(key, new Response(blob, { headers: response.headers, status: response.status, statusText: response.statusText }));
      }
      completed += 1;
      onProgress(completed, tiles.length);
    }
  };
  await Promise.all(Array.from({ length: 4 }, worker));
  const manifest = { version: MAP_VERSION, tile_template: MAP_TILE_URL, tile_count: tiles.length, min_zoom: 12, max_zoom: 16, generated_at: new Date().toISOString() };
  await cache.put(manifestUrl, new Response(JSON.stringify(manifest), { headers: { 'Content-Type': 'application/json' } }));
  if (navigator.storage?.persist) await navigator.storage.persist().catch(() => false);
  return { count: tiles.length, bytes };
}

export async function hasOfflineDistrictMap() {
  if (!('caches' in window)) return false;
  const oldVersions = (await caches.keys()).filter((name) => name.startsWith('q1-tourism-map-v') && name !== OFFLINE_MAP_CACHE);
  await Promise.all(oldVersions.map((name) => caches.delete(name)));
  const cache = await caches.open(OFFLINE_MAP_CACHE);
  const saved = await cache.match(new URL('/offline-map-manifest.json', window.location.origin).href);
  if (!saved) return false;
  const manifest = await saved.json();
  if (manifest.tile_template !== MAP_TILE_URL) {
    await caches.delete(OFFLINE_MAP_CACHE);
    return false;
  }
  return true;
}
