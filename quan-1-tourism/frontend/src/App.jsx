import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import demoPois from './data/demoPois.json';
import { GeofenceEngine } from './services/geofenceEngine.js';
import { cacheDistrictTiles, hasOfflineDistrictMap, listDistrictTiles, OFFLINE_MAP_CACHE } from './services/offlineMap.js';
import AdminPanel from './components/AdminPanel.jsx';
import MapView from './components/MapView.jsx';
import './account.css';

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000/api/v1' : `${window.location.origin}/api/v1`);
const OFFLINE_CACHE = 'q1-tourism-offline-v1';
const isEnglish = (locale) => locale === 'en-US';

function readCachedUserSession() {
  try {
    const session = JSON.parse(sessionStorage.getItem('q1-user-session') || 'null');
    const encoded = session?.access_token?.split('.')[1];
    if (!session?.user || !encoded) return null;
    const claims = JSON.parse(atob(encoded.replace(/-/g, '+').replace(/_/g, '/')));
    return claims.exp * 1000 > Date.now() ? session : null;
  } catch { return null; }
}

function storeUserSession(session) {
  try { sessionStorage.setItem('q1-user-session', JSON.stringify(session)); } catch { /* Session storage may be disabled. */ }
}

async function readOfflinePois() {
  if (!('caches' in window)) return [];
  const cache = await caches.open(OFFLINE_CACHE);
  const cached = await cache.match(new URL('/offline-manifest.json', window.location.origin).href);
  if (!cached) return [];
  const manifest = await cached.json();
  return (manifest.packages || []).map((item) => ({
    ...item.poi,
    localizations: item.localizations,
    audio: Object.fromEntries(Object.entries(item.audio || {}).map(([locale, asset]) => [locale, { ...asset, audio_url: asset.offline_url || asset.audio_url }])),
  }));
}

function App() {
  const [authState, setAuthState] = useState('checking');
  const [authMode, setAuthMode] = useState('login');
  const [authToken, setAuthToken] = useState('');
  const [authUser, setAuthUser] = useState(null);
  const [authError, setAuthError] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [authUsername, setAuthUsername] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [pois, setPois] = useState(demoPois);
  const [selected, setSelected] = useState(demoPois[0]);
  const [locale, setLocale] = useState(localStorage.getItem('q1-locale') || 'vi-VN');
  const [position, setPosition] = useState(null);
  const [locationMessage, setLocationMessage] = useState('Bản đồ đang ở trung tâm Quận 1');
  const [apiState, setApiState] = useState('loading');
  const [playing, setPlaying] = useState(false);
  const [consent, setConsent] = useState(localStorage.getItem('q1-analytics-consent') === 'true');
  const [consentToken, setConsentToken] = useState(localStorage.getItem('q1-analytics-token') || '');
  const [analyticsSession] = useState(() => localStorage.getItem('q1-session') || (() => { const id = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`; localStorage.setItem('q1-session', id); return id; })());
  const [inside, setInside] = useState(null);
  const [view, setView] = useState(() => window.location.pathname.replace(/\/$/, '') === '/admin' ? 'admin-app' : 'all');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [favorites, setFavorites] = useState([]);
  const [offlineReady, setOfflineReady] = useState(false);
  const [offlineMapReady, setOfflineMapReady] = useState(false);
  const [offlineProgress, setOfflineProgress] = useState(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [recenterKey, setRecenterKey] = useState(0);
  const [installPrompt, setInstallPrompt] = useState(null);
  const [installMessage, setInstallMessage] = useState('');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const engineRef = useRef(null);
  const audioRef = useRef(null);
  const speakRef = useRef(null);
  const audioUnlockedRef = useRef(false);
  const narrationTimerRef = useRef(null);

  const userApi = useCallback(async (path, options = {}) => {
    const send = (token) => fetch(`${API}${path}`, { ...options, credentials: 'include', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } });
    let response = await send(authToken);
    if (response.status === 401 && !path.startsWith('/auth/')) {
      const refresh = await fetch(`${API}/auth/refresh`, { method: 'POST', credentials: 'include' });
      if (refresh.ok) {
        const session = await refresh.json();
        storeUserSession(session);
        setAuthToken(session.access_token);
        setAuthUser(session.user);
        response = await send(session.access_token);
      } else {
        setAuthState('signed-out'); setAuthToken(''); setAuthUser(null);
      }
    }
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `API ${response.status}`);
    return data;
  }, [authToken]);

  useEffect(() => {
    if (window.location.pathname.replace(/\/$/, '') === '/admin') { setAuthState('signed-out'); return undefined; }
    let alive = true;
    fetch(`${API}/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then(async (response) => response.ok ? response.json() : null)
      .then((session) => {
        if (!alive) return;
        if (session?.access_token && session.user?.role === 'USER') {
          storeUserSession(session);
          setAuthToken(session.access_token); setAuthUser(session.user); setAuthState('signed-in');
        } else {
          const cached = readCachedUserSession();
          if (cached) { setAuthToken(cached.access_token); setAuthUser(cached.user); setAuthState('signed-in'); }
          else setAuthState('signed-out');
        }
      }).catch(() => {
        if (!alive) return;
        const cached = readCachedUserSession();
        if (cached) { setAuthToken(cached.access_token); setAuthUser(cached.user); setAuthState('signed-in'); }
        else setAuthState('signed-out');
      });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (authState !== 'signed-in') return;
    let alive = true;
    userApi('/user/favorites').then((result) => {
      if (!alive) return;
      setFavorites(result.data || []);
      try { sessionStorage.setItem(`q1-favorites:${authUser?.username}`, JSON.stringify(result.data || [])); } catch { /* Cache is optional. */ }
    }).catch((error) => {
      if (!alive) return;
      try { setFavorites(JSON.parse(sessionStorage.getItem(`q1-favorites:${authUser?.username}`) || '[]')); } catch { setFavorites([]); }
      setLocationMessage(error.message);
    });
    return () => { alive = false; };
  }, [authState, authUser?.username, userApi]);

  const submitAuth = async (event) => {
    event.preventDefault(); setAuthBusy(true); setAuthError('');
    try {
      const endpoint = authMode === 'register' ? '/auth/register' : '/auth/login';
      const response = await fetch(`${API}${endpoint}`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: authUsername.trim(), password: authPassword }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Không thể đăng nhập');
      storeUserSession(data);
      setAuthToken(data.access_token); setAuthUser(data.user); setAuthState('signed-in'); setAuthPassword('');
    } catch (error) { setAuthError(error.message); }
    finally { setAuthBusy(false); }
  };

  const signOut = async () => {
    try { await userApi('/auth/logout', { method: 'POST' }); } catch { /* Session is cleared locally when the API is offline. */ }
    clearTimeout(narrationTimerRef.current); audioRef.current?.pause(); window.speechSynthesis?.cancel(); setPlaying(false);
    try { sessionStorage.removeItem('q1-user-session'); } catch { /* Optional cache. */ }
    setAuthToken(''); setAuthUser(null); setFavorites([]); setAuthState('signed-out');
  };

  const toggleFavorite = async (poiId) => {
    const wasFavorite = favorites.includes(poiId);
    const next = wasFavorite ? favorites.filter((id) => id !== poiId) : [...favorites, poiId];
    setFavorites(next);
    try { sessionStorage.setItem(`q1-favorites:${authUser?.username}`, JSON.stringify(next)); } catch { /* Cache is optional. */ }
    const pendingKey = `q1-favorite-sync:${authUser?.username}`;
    const queueChange = () => {
      try {
        const queue = JSON.parse(sessionStorage.getItem(pendingKey) || '[]').filter((item) => item.poi_id !== poiId);
        queue.push({ poi_id: poiId, favorite: !wasFavorite });
        sessionStorage.setItem(pendingKey, JSON.stringify(queue));
      } catch { /* Optional offline synchronization queue. */ }
    };
    if (!navigator.onLine) { queueChange(); return; }
    try {
      await userApi(`/user/favorites/${encodeURIComponent(poiId)}`, { method: wasFavorite ? 'DELETE' : 'PUT' });
    } catch (error) {
      if (error instanceof TypeError) { queueChange(); setLocationMessage('Đã lưu yêu thích trên thiết bị; sẽ đồng bộ khi có mạng.'); return; }
      setFavorites((current) => wasFavorite ? [...new Set([...current, poiId])] : current.filter((id) => id !== poiId));
      setLocationMessage(error.message);
    }
  };

  useEffect(() => {
    if (!isOnline || authState !== 'signed-in' || !authUser?.username) return;
    let cancelled = false;
    const pendingKey = `q1-favorite-sync:${authUser.username}`;
    (async () => {
      try {
        const queue = JSON.parse(sessionStorage.getItem(pendingKey) || '[]');
        for (const change of queue) {
          await userApi(`/user/favorites/${encodeURIComponent(change.poi_id)}`, { method: change.favorite ? 'PUT' : 'DELETE' });
        }
        if (queue.length) sessionStorage.removeItem(pendingKey);
        const result = await userApi('/user/favorites');
        if (!cancelled) {
          setFavorites(result.data || []);
          sessionStorage.setItem(`q1-favorites:${authUser.username}`, JSON.stringify(result.data || []));
        }
      } catch { /* Keep the local list and queued changes until the API is reachable. */ }
    })();
    return () => { cancelled = true; };
  }, [authState, authUser?.username, isOnline, userApi]);

  useEffect(() => {
    const syncRoute = () => setView(window.location.pathname.replace(/\/$/, '') === '/admin' ? 'admin-app' : 'all');
    window.addEventListener('popstate', syncRoute);
    return () => window.removeEventListener('popstate', syncRoute);
  }, []);
  const openAdmin = () => {
    if (window.location.pathname !== '/admin') window.history.pushState({}, '', '/admin');
    setView('admin-app');
    setMobileMenuOpen(false);
  };
  const closeAdmin = () => {
    if (window.location.pathname === '/admin') window.history.pushState({}, '', '/');
    setView('all');
  };

  const sendAnalytics = useCallback((eventType, poiId = null, metadata = {}) => {
    if (!consent || !consentToken) return;
    fetch(`${API}/analytics/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ consent_token: consentToken, session_id: analyticsSession, event_type: eventType, poi_id: poiId, metadata }) }).catch(() => {});
  }, [analyticsSession, consent, consentToken]);

  useEffect(() => {
    if ('serviceWorker' in navigator && import.meta.env.PROD) navigator.serviceWorker.register('/sw.js').catch(() => {});
    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    const onInstallPrompt = (event) => { event.preventDefault(); setInstallPrompt(event); };
    const onInstalled = () => { setInstallPrompt(null); setInstallMessage(isEnglish(locale) ? 'App added to your home screen.' : 'Đã cài ứng dụng vào màn hình chính.'); };
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    window.addEventListener('beforeinstallprompt', onInstallPrompt);
    window.addEventListener('appinstalled', onInstalled);
    let alive = true;
    readOfflinePois().then((cached) => { if (alive && cached.length) setOfflineReady(true); }).catch(() => {});
    hasOfflineDistrictMap().then((ready) => { if (alive) setOfflineMapReady(ready); }).catch(() => {});
    fetch(`${API}/poi/manifest`).then((response) => { if (!response.ok) throw new Error('API error'); return response.json(); })
      .then((result) => {
        const records = result.data || [];
        if (!alive) return;
        if (records.length) { setPois(records); setSelected(records[0]); setApiState('connected'); }
        else setApiState('demo');
      })
      .catch(async () => {
        if (!alive) return;
        setApiState('offline');
        try {
          const cached = await readOfflinePois();
          if (alive && cached.length) { setPois(cached); setSelected(cached[0]); setOfflineReady(true); }
        } catch { /* Offline POI cache is optional. */ }
      });
    return () => {
      alive = false;
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
      window.removeEventListener('beforeinstallprompt', onInstallPrompt);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  const enterPoi = useCallback((poi) => {
    setInside(poi); setSelected(poi); sendAnalytics('poi_view', poi.id, { locale });
  }, [locale, sendAnalytics]);
  useEffect(() => { engineRef.current = new GeofenceEngine(pois, enterPoi, () => setInside(null)); }, [pois, enterPoi]);
  useEffect(() => {
    if (authState !== 'signed-in') return undefined;
    if (!navigator.geolocation) { setLocationMessage('Thiết bị không hỗ trợ định vị'); return undefined; }
    const watch = navigator.geolocation.watchPosition(({ coords }) => {
      const next = { latitude: coords.latitude, longitude: coords.longitude };
      setPosition(next); setLocationMessage('Đang cập nhật vị trí trên thiết bị'); engineRef.current?.checkPosition(next);
    }, () => setLocationMessage('Chưa có vị trí · Cho phép GPS để bật thuyết minh tự động'), { enableHighAccuracy: true, maximumAge: 5000, timeout: 12000 });
    return () => navigator.geolocation.clearWatch(watch);
  }, [authState]);
  useEffect(() => () => window.speechSynthesis?.cancel(), []);

  const categories = useMemo(() => [...new Set(pois.map((poi) => poi.category).filter(Boolean))].sort(), [pois]);
  const visiblePois = useMemo(() => {
    const term = search.trim().toLocaleLowerCase(locale);
    return pois.filter((poi) => {
      if (view === 'favorites' && !favorites.includes(poi.id)) return false;
      if (category !== 'all' && (poi.category || '') !== category) return false;
      if (!term) return true;
      return [poi.title, poi.title_en, poi.slug, poi.category].some((value) => value?.toLocaleLowerCase(locale).includes(term));
    });
  }, [pois, search, locale, view, favorites, category]);
  useEffect(() => {
    if (visiblePois.length && !visiblePois.some((poi) => poi.id === selected?.id)) setSelected(visiblePois[0]);
  }, [visiblePois, selected]);
  const distance = useMemo(() => {
    if (!position || !selected) return null;
    const [lng, lat] = selected.location.coordinates;
    const rad = Math.PI / 180, dLat = (lat - position.latitude) * rad, dLng = (lng - position.longitude) * rad;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(position.latitude * rad) * Math.cos(lat * rad) * Math.sin(dLng / 2) ** 2;
    return Math.round(6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
  }, [position, selected]);

  const startNarrationLimit = () => {
    clearTimeout(narrationTimerRef.current);
    narrationTimerRef.current = window.setTimeout(() => {
      audioRef.current?.pause();
      window.speechSynthesis?.cancel();
      setPlaying(false);
      setLocationMessage('Đã dừng thuyết minh sau 1 phút.');
    }, 60_000);
  };

  const speak = (fromUser = false) => {
    if (!selected) return;
    if (fromUser) audioUnlockedRef.current = true;
    if (!audioUnlockedRef.current) { setLocationMessage('Bạn đã đến gần địa điểm. Chạm “Nghe câu chuyện” để bật thuyết minh.'); return; }
    const audioAsset = selected.audio?.[locale];
    const assetUrl = apiState === 'offline' && !audioAsset?.offline_url ? null : audioAsset?.audio_url;
    if (assetUrl && audioRef.current) {
      if (playing) { clearTimeout(narrationTimerRef.current); audioRef.current.pause(); setPlaying(false); return; }
      audioRef.current.play().then(() => { startNarrationLimit(); setPlaying(true); sendAnalytics('narration_started', selected.id, { locale }); }).catch(() => { setPlaying(false); setLocationMessage('Không phát được audio. Kiểm tra kết nối hoặc thử lại.'); });
      return;
    }
    if (!('speechSynthesis' in window)) { setLocationMessage('Thiết bị chưa hỗ trợ đọc văn bản.'); return; }
    if (playing) { clearTimeout(narrationTimerRef.current); window.speechSynthesis.cancel(); setPlaying(false); return; }
    const utterance = new SpeechSynthesisUtterance(isEnglish(locale) ? (selected.localizations?.[locale] || selected.summary_en || selected.summary_vi) : (selected.localizations?.[locale] || selected.summary_vi));
    utterance.lang = locale; utterance.rate = 0.92;
    utterance.onstart = () => { startNarrationLimit(); sendAnalytics('narration_started', selected.id, { locale }); };
    utterance.onend = () => { clearTimeout(narrationTimerRef.current); setPlaying(false); sendAnalytics('narration_completed', selected.id, { locale }); };
    utterance.onerror = () => { clearTimeout(narrationTimerRef.current); setPlaying(false); setLocationMessage('Không phát được thuyết minh. Chạm nút nghe để thử lại.'); };
    window.speechSynthesis.cancel(); window.speechSynthesis.speak(utterance); setPlaying(true);
  };
  speakRef.current = speak;
  useEffect(() => {
    if (!inside) return undefined;
    const timer = window.setTimeout(() => speakRef.current?.(), 250);
    return () => window.clearTimeout(timer);
  }, [inside]);
  useEffect(() => { clearTimeout(narrationTimerRef.current); audioRef.current?.pause(); window.speechSynthesis?.cancel(); setPlaying(false); }, [selected?.id, locale]);

  const selectPoi = (poi) => { setSelected(poi); sendAnalytics('poi_view', poi.id, { locale }); };
  const titleOf = (poi) => isEnglish(locale) ? (poi.title_en || poi.title) : poi.title;
  const descriptionOf = (poi) => {
    const summary = isEnglish(locale) ? (poi.localizations?.[locale] || poi.summary_en || poi.summary_vi) : (poi.localizations?.[locale] || poi.summary_vi);
    const facts = [poi.address && `${isEnglish(locale) ? 'Address' : 'Địa chỉ'}: ${poi.address}`, poi.opening_hours && `${isEnglish(locale) ? 'Opening hours' : 'Giờ mở cửa'}: ${poi.opening_hours}`];
    return [summary, ...facts].filter(Boolean).join(' · ');
  };
  const audioSource = (url) => url?.startsWith('http') ? url : `${url?.startsWith('/offline-audio/') ? window.location.origin : new URL(API).origin}${url}`;

  const changeLocale = (value) => { setLocale(value); localStorage.setItem('q1-locale', value); window.speechSynthesis?.cancel(); setPlaying(false); };
  const toggleConsent = async () => {
    try {
      const result = await fetch(`${API}/analytics/consent`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accepted: !consent, token: consentToken || null }) });
      if (!result.ok) throw new Error('Không lưu được lựa chọn consent');
      const data = await result.json();
      setConsent(data.accepted); localStorage.setItem('q1-analytics-consent', String(data.accepted));
      setConsentToken(data.consent_token || '');
      if (data.consent_token) localStorage.setItem('q1-analytics-token', data.consent_token); else localStorage.removeItem('q1-analytics-token');
    } catch { setLocationMessage('Không thể lưu lựa chọn phân tích; thử lại khi có mạng.'); }
  };
  const downloadOffline = async () => {
    if (!('caches' in window)) { setLocationMessage('Trình duyệt này chưa hỗ trợ lưu gói ngoại tuyến.'); return; }
    try {
      setOfflineProgress({ done: 0, total: 0 });
      const response = await fetch(`${API}/offline/manifest`);
      if (!response.ok) throw new Error('Không tải được danh sách địa điểm ngoại tuyến');
      const manifest = await response.json();
      const cache = await caches.open(OFFLINE_CACHE);
      const packages = manifest.packages || [];
      const contentTotal = packages.length + packages.reduce((sum, item) => sum + Object.keys(item.audio || {}).length, 0);
      const tiles = listDistrictTiles(pois);
      const total = Math.max(1, contentTotal + tiles.length);
      let done = 0;
      let failedAudio = 0;
      let mapIssue = '';
      setOfflineProgress({ done, total });
      const origin = new URL(API).origin;
      for (const pkg of packages) {
        for (const audio of Object.values(pkg.audio || {})) {
          if (audio.audio_url) {
            try {
              const url = audio.audio_url.startsWith('http') ? audio.audio_url : `${origin}${audio.audio_url}`;
              const audioResponse = await fetch(url);
              if (audioResponse.ok) {
                const offlineUrl = `/offline-audio/${crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`}.mp3`;
                await cache.put(new URL(offlineUrl, window.location.origin).href, audioResponse.clone());
                audio.offline_url = offlineUrl;
              } else failedAudio += 1;
            } catch { failedAudio += 1; /* Text stories still work through speech synthesis. */ }
          }
          done += 1; setOfflineProgress({ done, total });
        }
        done += 1; setOfflineProgress({ done, total });
      }
      await cache.put(new URL('/offline-manifest.json', window.location.origin).href, new Response(JSON.stringify(manifest), { headers: { 'Content-Type': 'application/json' } }));
      setOfflineReady(true);
      if (tiles.length) {
        try {
          const mapResult = await cacheDistrictTiles(pois, (mapDone) => setOfflineProgress({ done: contentTotal + mapDone, total }));
          setOfflineMapReady(mapResult.count > 0);
        } catch (error) { setOfflineMapReady(false); mapIssue = error.message; }
      }
      setOfflineReady(true); setOfflineProgress({ done: total, total }); sendAnalytics('offline_downloaded', null, { source: 'all-pois' });
      window.setTimeout(() => setOfflineProgress(null), 400);
      const mapMessage = mapIssue || (tiles.length ? (isEnglish(locale) ? 'map tiles saved' : 'đã lưu ô bản đồ') : (isEnglish(locale) ? 'map tiles unavailable: configure a permitted provider' : 'chưa lưu bản đồ nền: cần cấu hình nhà cung cấp tile cho phép tải offline'));
      const mediaMessage = failedAudio ? (isEnglish(locale) ? `; ${failedAudio} audio file(s) were unavailable, text narration remains available` : `; ${failedAudio} tệp audio chưa tải được, vẫn có thể nghe bằng giọng đọc của thiết bị`) : '';
      setLocationMessage(isEnglish(locale) ? `Saved ${packages.length} places offline; ${mapMessage}${mediaMessage}.` : `Đã lưu ${packages.length} địa điểm để dùng offline; ${mapMessage}${mediaMessage}.`);
    } catch (error) { setOfflineProgress(null); setLocationMessage(error.message || 'Tải ngoại tuyến thất bại'); }
  };
  const clearOffline = async () => {
    if ('caches' in window) await caches.delete(OFFLINE_CACHE);
    if ('caches' in window) await caches.delete(OFFLINE_MAP_CACHE);
    setOfflineReady(false); setOfflineMapReady(false); setLocationMessage(isEnglish(locale) ? 'Offline package removed.' : 'Đã xóa gói ngoại tuyến.');
  };
  const useMyLocation = () => {
    if (!navigator.geolocation) { setLocationMessage('Thiết bị không hỗ trợ GPS.'); return; }
    if (!window.isSecureContext && !['localhost', '127.0.0.1'].includes(window.location.hostname)) { setLocationMessage('GPS cần HTTPS hoặc localhost.'); return; }
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      const point = { latitude: coords.latitude, longitude: coords.longitude };
      setPosition(point); setRecenterKey((key) => key + 1); engineRef.current?.checkPosition(point); setLocationMessage('Đã cho phép GPS; vị trí chỉ xử lý trên thiết bị.');
    }, (error) => setLocationMessage(error.code === error.PERMISSION_DENIED ? 'Bạn đã chặn GPS. Hãy bật quyền Vị trí cho trang web trong trình duyệt.' : 'Không lấy được vị trí GPS. Hãy bật GPS và thử lại.'), { enableHighAccuracy: true, timeout: 12000, maximumAge: 5000 });
  };
  const installApp = async () => {
    if (!installPrompt) { setInstallMessage(isEnglish(locale) ? 'Use your browser menu and choose “Add to Home Screen”.' : 'Mở menu trình duyệt rồi chọn “Thêm vào màn hình chính”.'); return; }
    await installPrompt.prompt();
    const choice = await installPrompt.userChoice;
    setInstallMessage(choice.outcome === 'accepted' ? 'Đang cài ứng dụng…' : 'Bạn có thể cài ứng dụng sau trong menu trình duyệt.');
    setInstallPrompt(null);
  };
  const setListView = (nextView) => { setView(nextView); setMobileMenuOpen(false); document.getElementById('places')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); };

  if (view === 'admin-app') return <AdminPanel onClose={closeAdmin} />;
  if (authState === 'checking') return <main className="admin-login-wrap"><section className="admin-login"><span className="eyebrow">QUẬN 1 TOURISM</span><h1>Đang kiểm tra phiên đăng nhập</h1></section></main>;
  if (authState !== 'signed-in') return <main className="admin-login-wrap"><form className="admin-login" onSubmit={submitAuth}>
    <span className="eyebrow">QUẬN 1 TOURISM · TÀI KHOẢN</span>
    <h1>{authMode === 'register' ? 'Tạo tài khoản khách' : 'Đăng nhập khám phá'}</h1>
    <p>{authMode === 'register' ? 'Tạo tài khoản để đồng bộ địa điểm yêu thích giữa các lần sử dụng.' : 'Đăng nhập để xem các địa điểm yêu thích đã lưu theo tài khoản.'}</p>
    <label>Tên đăng nhập<input value={authUsername} onChange={(event) => setAuthUsername(event.target.value)} autoComplete="username" minLength="3" maxLength="160" required /></label>
    <label>Mật khẩu<input type="password" value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} autoComplete={authMode === 'register' ? 'new-password' : 'current-password'} minLength={authMode === 'register' ? 10 : 1} required /></label>
    {authError && <div className="admin-message" role="alert">{authError}</div>}
    <button className="admin-primary" disabled={authBusy}>{authBusy ? 'Đang xử lý…' : authMode === 'register' ? 'Đăng ký' : 'Đăng nhập'}</button>
    <button className="admin-text-button" type="button" onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthError(''); }}>{authMode === 'register' ? 'Đã có tài khoản? Đăng nhập' : 'Chưa có tài khoản? Đăng ký'}</button>
    <a className="admin-text-button" href="/admin">Đăng nhập quản trị viên</a>
  </form></main>;
  return <main className="app-shell">
    <a className="skip-link" href="#explore">{isEnglish(locale) ? 'Skip to places' : 'Bỏ qua đến danh sách địa điểm'}</a>
    <header className="topbar" id="top">
      <a className="brand" href="#top" aria-label="Quận 1 Tourism"><span className="brand-mark">Q1</span><span><b>QUẬN 1</b><small>TOURISM</small></span></a>
      <nav className="desktop-nav" aria-label={isEnglish(locale) ? 'Main navigation' : 'Điều hướng chính'}>
        <a className="nav-active" href="#explore">{isEnglish(locale) ? 'Explore' : 'Khám phá'}</a><a href="#places">{isEnglish(locale) ? 'Places' : 'Địa điểm'}</a><button className="nav-admin" onClick={openAdmin}>{isEnglish(locale) ? 'Admin' : 'Quản trị'}</button>
      </nav>
      <div className="header-tools"><span className="user-greeting">{authUser?.username}</span><button className="user-logout" onClick={signOut}>Đăng xuất</button><span className={`api-dot ${apiState}`} title={apiState === 'connected' ? 'API đã kết nối' : apiState === 'offline' ? 'Đang ngoại tuyến' : 'Đang dùng dữ liệu mẫu'} /><select aria-label={isEnglish(locale) ? 'Language' : 'Ngôn ngữ'} value={locale} onChange={(event) => changeLocale(event.target.value)}><option value="vi-VN">VI</option><option value="en-US">EN</option></select><button className="menu-toggle" aria-label={mobileMenuOpen ? 'Đóng menu' : 'Mở menu'} aria-expanded={mobileMenuOpen} onClick={() => setMobileMenuOpen((open) => !open)}>{mobileMenuOpen ? '×' : '☰'}</button></div>
    </header>
    {mobileMenuOpen && <nav className="mobile-menu" aria-label="Menu"><a href="#explore" onClick={() => setMobileMenuOpen(false)}>{isEnglish(locale) ? 'Explore' : 'Khám phá'}</a><a href="#places" onClick={() => setMobileMenuOpen(false)}>{isEnglish(locale) ? 'Places' : 'Địa điểm'}</a><button onClick={openAdmin}>{isEnglish(locale) ? 'Admin' : 'Quản trị'}</button></nav>}
    <section className="hero"><div className="hero-copy"><span className="eyebrow"><i /> {isEnglish(locale) ? 'YOUR CITY, YOUR STORY' : 'THÀNH PHỐ KỂ CHUYỆN'}</span><h1>{isEnglish(locale) ? <>Meet Saigon<br /><em>one story at a time.</em></> : <>Chạm vào Sài Gòn,<br /><em>nghe từng câu chuyện.</em></>}</h1><p>{isEnglish(locale) ? 'Walk at your own pace. When you reach a landmark, let its story find you.' : 'Tản bộ theo nhịp riêng. Khi bạn đến gần một địa danh, câu chuyện nơi đó sẽ tự tìm đến bạn.'}</p><a className="hero-link" href="#explore">{isEnglish(locale) ? 'Start exploring' : 'Bắt đầu khám phá'} <span>↘</span></a></div><div className="hero-art" aria-label="Minh họa các mái nhà và cây xanh Sài Gòn"><div className="sun"/><div className="skyline"><span className="tower"/><span className="roof"/><span className="roof roof-two"/><span className="tree tree-one"/><span className="tree tree-two"/><span className="ground"/></div><div className="art-caption"><span>10°46′ N · 106°42′ E</span><span>HO CHI MINH CITY</span></div><span className="art-stamp">WALK<br/>SLOWLY</span></div></section>
    <section className="explore-section" id="explore">
      <div className="section-heading"><div><span className="eyebrow">01 / {isEnglish(locale) ? 'THE NEIGHBOURHOOD' : 'KHU PHỐ'}</span><h2>{isEnglish(locale) ? 'A little closer.' : 'Gần bạn hơn.'}</h2><p>{isEnglish(locale) ? 'Explore landmarks around District 1.' : 'Khám phá những dấu mốc quanh Quận 1.'}</p></div><span className="place-count">{String(visiblePois.length).padStart(2, '0')} <small>{isEnglish(locale) ? 'PLACES' : 'ĐỊA ĐIỂM'}</small></span></div>
      <div className="discovery-controls"><label className="search-field"><span aria-hidden="true">⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={isEnglish(locale) ? 'Search places' : 'Tìm địa điểm'} aria-label={isEnglish(locale) ? 'Search places' : 'Tìm địa điểm'} /></label><div className="filter-row" role="group" aria-label={isEnglish(locale) ? 'Place filters' : 'Lọc địa điểm'}><button className={view === 'all' ? 'filter-active' : ''} onClick={() => setView('all')}>{isEnglish(locale) ? 'All' : 'Tất cả'}</button><button className={view === 'favorites' ? 'filter-active' : ''} onClick={() => setView('favorites')}>♥ {isEnglish(locale) ? 'Saved' : 'Yêu thích'} ({favorites.length})</button><select aria-label={isEnglish(locale) ? 'Category' : 'Danh mục'} value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">{isEnglish(locale) ? 'All categories' : 'Mọi danh mục'}</option>{categories.map((item) => <option key={item} value={item}>{item}</option>)}</select></div></div>
      <div className="explore-grid"><div className="map-panel"><MapView pois={visiblePois} selected={selected} position={position} onSelect={selectPoi} recenterKey={recenterKey} /><div className="map-label"><span className="live-pulse"/> {position ? (isEnglish(locale) ? 'YOUR LOCATION' : 'VỊ TRÍ CỦA BẠN') : (isEnglish(locale) ? 'DISTRICT 1, HCMC' : 'QUẬN 1, TP. HỒ CHÍ MINH')}</div><button className="recenter-button" onClick={useMyLocation} aria-label={isEnglish(locale) ? 'Center map on my location' : 'Đưa bản đồ đến vị trí của tôi'}>◎ {isEnglish(locale) ? 'My location' : 'Vị trí của tôi'}</button>{!isOnline && <div className="offline-map-note">{offlineMapReady ? (isEnglish(locale) ? 'Saved map tiles are available offline.' : 'Các ô bản đồ đã lưu đang dùng ngoại tuyến.') : (isEnglish(locale) ? 'Map tiles need an internet connection. Saved places and stories remain available.' : 'Bản đồ nền cần mạng. Địa điểm và câu chuyện đã lưu vẫn dùng được.')}</div>}<div className="map-footer"><span aria-live="polite">✳ {locationMessage}</span><span>© OpenStreetMap</span></div></div>
        <aside className="place-panel" id="places"><div className="list-heading"><span>{view === 'favorites' ? (isEnglish(locale) ? 'SAVED STORIES' : 'ĐỊA ĐIỂM YÊU THÍCH') : (isEnglish(locale) ? 'NEARBY STORIES' : 'CÂU CHUYỆN QUANH ĐÂY')}</span><span>{visiblePois.length}</span></div><div className="place-list">{visiblePois.map((poi, index) => <div key={poi.id} className={`place-row ${selected?.id === poi.id ? 'place-active' : ''}`}><button className="place-select" onClick={() => selectPoi(poi)}><span className="place-number">{String(index + 1).padStart(2, '0')}</span><span className="place-info"><b>{titleOf(poi)}</b><small>{poi.category || (isEnglish(locale) ? 'HERITAGE & CULTURE' : 'DI SẢN & VĂN HÓA')}</small></span><span className="place-arrow">↗</span></button><button className={`row-favorite ${favorites.includes(poi.id) ? 'is-favorite' : ''}`} aria-label={favorites.includes(poi.id) ? 'Bỏ yêu thích' : 'Thêm yêu thích'} onClick={() => toggleFavorite(poi.id)}>{favorites.includes(poi.id) ? '♥' : '♡'}</button></div>)}</div>
          {!visiblePois.length && <p className="empty-list">{isEnglish(locale) ? 'No places match this filter.' : 'Không tìm thấy địa điểm phù hợp.'}</p>}
          {selected && visiblePois.some((poi) => poi.id === selected.id) && <article className="story-card"><div className="story-top"><span className="eyebrow">{isEnglish(locale) ? 'A STORY FOR THIS PLACE' : 'CÂU CHUYỆN ĐỊA ĐIỂM'}</span><span className="story-distance">{distance == null ? 'Q1' : distance < 1000 ? `${distance} m` : `${(distance / 1000).toFixed(1)} km`}</span></div><h3>{titleOf(selected)}</h3><p>{descriptionOf(selected)}</p>{selected.audio?.[locale]?.audio_url && <audio ref={audioRef} src={audioSource(selected.audio[locale].audio_url)} onEnded={() => { clearTimeout(narrationTimerRef.current); setPlaying(false); sendAnalytics('narration_completed', selected.id, { locale }); }} onPause={() => setPlaying(false)} onPlay={() => setPlaying(true)} />}<button className={`listen-button ${playing ? 'is-playing' : ''}`} onClick={() => speak(true)}><span className="play-icon">{playing ? 'Ⅱ' : '▶'}</span><span>{playing ? (isEnglish(locale) ? 'Pause narration' : 'Tạm dừng thuyết minh') : (isEnglish(locale) ? 'Listen to the story' : 'Nghe câu chuyện')}</span><span className="listen-lang">{locale === 'vi-VN' ? 'VI' : 'EN'} · TTS</span></button><div className="story-actions"><button className={favorites.includes(selected.id) ? 'is-favorite' : ''} onClick={() => toggleFavorite(selected.id)}>{favorites.includes(selected.id) ? '♥' : '♡'} {isEnglish(locale) ? 'Save place' : 'Yêu thích'}</button></div>{inside?.id === selected.id && <button className="skip-button" onClick={() => { clearTimeout(narrationTimerRef.current); window.speechSynthesis?.cancel(); audioRef.current?.pause(); setPlaying(false); setLocationMessage('Đã bỏ qua thuyết minh địa điểm này'); }}>{isEnglish(locale) ? 'Skip narration' : 'Bỏ qua thuyết minh'} ↷</button>}<div className="source-note">{isEnglish(locale) ? 'SOURCE' : 'NGUỒN'} · {selected.source_ref?.name || 'QUẬN 1 TOURISM'}{selected.source_ref?.url && <a href={selected.source_ref.url} target="_blank" rel="noreferrer"> ↗</a>}</div></article>}</aside></div>
    </section>
    <section className="nearby-banner"><span className="banner-icon">◎</span><div><b>{inside ? `${isEnglish(locale) ? 'You are near' : 'Bạn đang ở gần'} ${titleOf(inside)}` : (isEnglish(locale) ? 'Let the city guide you.' : 'Để thành phố dẫn lối.')}</b><p>{inside ? (isEnglish(locale) ? 'Tap play to hear the story.' : 'Chạm nút nghe để phát câu chuyện.') : (isEnglish(locale) ? 'Enable location to hear stories as you walk.' : 'Bật vị trí để nghe chuyện kể trên đường đi.')}</p></div><div className="offline-actions"><button className="offline-button" onClick={downloadOffline} disabled={Boolean(offlineProgress)}>{offlineProgress ? `↓ ${offlineProgress.done}/${offlineProgress.total}` : offlineReady ? (isEnglish(locale) ? '✓ SAVED OFFLINE' : '✓ ĐÃ LƯU OFFLINE') : (isEnglish(locale) ? '↓ SAVE OFFLINE' : '↓ TẢI GÓI OFFLINE')}</button>{offlineReady && <button className="clear-offline-button" onClick={clearOffline}>{isEnglish(locale) ? 'Remove' : 'Xóa gói'}</button>}{offlineProgress && <progress max={offlineProgress.total} value={offlineProgress.done} aria-label={isEnglish(locale) ? 'Offline download progress' : 'Tiến độ tải ngoại tuyến'} />}</div><button className="location-button" onClick={useMyLocation}>{isEnglish(locale) ? 'USE MY LOCATION' : 'DÙNG VỊ TRÍ CỦA TÔI'} ↗</button><button className="install-button" onClick={installApp}>{isEnglish(locale) ? 'INSTALL APP' : 'CÀI ỨNG DỤNG'} ↓</button></section>
    {installMessage && <div className="install-message" role="status">{installMessage}<button aria-label="Đóng thông báo" onClick={() => setInstallMessage('')}>×</button></div>}
    <footer><a className="brand footer-brand" href="#top"><span className="brand-mark">Q1</span><span><b>QUẬN 1</b><small>TOURISM</small></span></a><span>MADE FOR THE CURIOUS · HO CHI MINH CITY</span><button className="consent-button" onClick={toggleConsent}>{consent ? '✓ ' : ''}{isEnglish(locale) ? 'Analytics consent' : 'Đồng ý phân tích'} · {consent ? (isEnglish(locale) ? 'ON' : 'BẬT') : (isEnglish(locale) ? 'OFF' : 'TẮT')}</button></footer>
    <nav className="mobile-nav" aria-label={isEnglish(locale) ? 'Quick navigation' : 'Điều hướng nhanh'}><a href="#explore">⌂<span>{isEnglish(locale) ? 'Explore' : 'Khám phá'}</span></a><button onClick={() => setListView('favorites')}>♥<span>{isEnglish(locale) ? 'Saved' : 'Yêu thích'}</span></button><button onClick={useMyLocation}>◎<span>{isEnglish(locale) ? 'GPS' : 'Vị trí'}</span></button><button onClick={openAdmin}>⚙<span>{isEnglish(locale) ? 'Admin' : 'Quản trị'}</span></button></nav>
  </main>;
}

export default App;
