import { Fragment, useEffect, useRef } from 'react';
import L from 'leaflet';
import { Circle, CircleMarker, MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { MAP_ATTRIBUTION, MAP_TILE_URL, OFFLINE_MAP_CACHE, tileUrl } from '../services/offlineMap.js';

const pinIcon = (label, active) => L.divIcon({ className: 'q1-leaflet-pin', html: `<span class="${active ? 'active' : ''}">${label}</span>`, iconSize: [30, 36], iconAnchor: [15, 34] });

function Recenter({ position, recenterKey }) {
  const map = useMap();
  const latestPosition = useRef(position);
  latestPosition.current = position;
  useEffect(() => {
    const point = latestPosition.current;
    if (point && recenterKey > 0) map.setView([point.latitude, point.longitude], Math.max(map.getZoom(), 16), { animate: true });
  }, [map, recenterKey]);
  return null;
}

function Basemap() {
  const map = useMap();
  useEffect(() => {
    if (!MAP_TILE_URL) return undefined;
    const layer = L.gridLayer({ attribution: MAP_ATTRIBUTION, minZoom: 12, maxZoom: 19, maxNativeZoom: 16 });
    layer.createTile = (coords, done) => {
      const tile = document.createElement('img');
      tile.alt = '';
      tile.setAttribute('role', 'presentation');
      const request = new Request(tileUrl(MAP_TILE_URL, coords.z, coords.x, coords.y), { mode: 'cors' });
      const loadTile = async () => {
        try {
          if (!('caches' in window)) {
            tile.onload = () => done(null, tile);
            tile.onerror = (error) => done(error, tile);
            tile.src = request.url;
            return;
          }
          const cache = await caches.open(OFFLINE_MAP_CACHE);
          let response = await cache.match(request);
          if (!response) {
            response = await fetch(request);
            if (response.ok && response.type !== 'opaque') await cache.put(request, response.clone());
          }
          if (!response.ok) throw new Error(`Map tile returned ${response.status}`);
          const objectUrl = URL.createObjectURL(await response.blob());
          tile.onload = () => { URL.revokeObjectURL(objectUrl); done(null, tile); };
          tile.onerror = (error) => { URL.revokeObjectURL(objectUrl); done(error, tile); };
          tile.src = objectUrl;
        } catch (error) {
          done(error, tile);
        }
      };
      loadTile();
      return tile;
    };
    layer.addTo(map);
    return () => { map.removeLayer(layer); };
  }, [map]);

  if (MAP_TILE_URL) return null;
  return <TileLayer attribution={MAP_ATTRIBUTION} url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />;
}

export default function MapView({ pois, selected, position, onSelect, recenterKey = 0 }) {
  return <MapContainer className="map-canvas" center={[10.7758, 106.6994]} zoom={15} scrollWheelZoom={false} zoomControl>
    <Recenter position={position} recenterKey={recenterKey} />
    <Basemap />
    {pois.map((poi, index) => {
      const [longitude, latitude] = poi.location.coordinates;
      const directions = `https://www.google.com/maps/dir/?api=1&destination=${latitude},${longitude}&travelmode=walking${position ? `&origin=${position.latitude},${position.longitude}` : ''}`;
      return <Fragment key={poi.id}><Circle center={[latitude, longitude]} radius={poi.geofence_radius || 30} pathOptions={{ color: selected?.id === poi.id ? '#c66a43' : '#6e8a71', weight: 1, fillOpacity: 0.08 }} /><Marker position={[latitude, longitude]} icon={pinIcon(String(index + 1).padStart(2, '0'), selected?.id === poi.id)} eventHandlers={{ click: () => onSelect(poi) }}><Popup><b>{poi.title}</b><br />Vùng tự động: {poi.geofence_radius || 30} m<button className="map-popup-button" onClick={() => onSelect(poi)}>Mở thuyết minh</button><a className="map-route-link" href={directions} target="_blank" rel="noreferrer">Chỉ đường đi bộ ↗</a></Popup></Marker></Fragment>;
    })}
    {position && <CircleMarker center={[position.latitude, position.longitude]} radius={7} pathOptions={{ color: '#fff', weight: 3, fillColor: '#377db5', fillOpacity: 1 }}><Popup>Vị trí của bạn</Popup></CircleMarker>}
  </MapContainer>;
}
