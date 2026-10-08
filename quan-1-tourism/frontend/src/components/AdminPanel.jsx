import { useCallback, useEffect, useState } from 'react';
import '../admin.css';

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000/api/v1' : `${window.location.origin}/api/v1`);
const emptyPoi = { title: '', title_en: '', slug: '', category: '', address: '', opening_hours: '', latitude: '10.7758', longitude: '106.6994', geofence_radius: '50', wikipedia_url: '', summary_vi: '', summary_en: '' };

export default function AdminPanel({ onClose }) {
  const [token, setToken] = useState('');
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [user, setUser] = useState(null);
  const [tab, setTab] = useState('pois');
  const [pois, setPois] = useState([]);
  const [contents, setContents] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [audit, setAudit] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [users, setUsers] = useState([]);
  const [poiForm, setPoiForm] = useState(emptyPoi);
  const [editingId, setEditingId] = useState(null);
  const [localizationId, setLocalizationId] = useState(null);
  const [localizationText, setLocalizationText] = useState('');
  const [newUser, setNewUser] = useState({ username: '', password: '', role: 'REVIEWER' });
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const api = useCallback(async (path, options = {}) => {
    const send = (accessToken) => {
      const headers = { 'Content-Type': 'application/json', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...options.headers };
      return fetch(`${API}${path}`, { ...options, headers, credentials: 'include' });
    };
    let response = await send(token);
    if (response.status === 401 && !['/admin/auth/login', '/admin/auth/refresh'].includes(path)) {
      const refreshResponse = await fetch(`${API}/admin/auth/refresh`, { method: 'POST', credentials: 'include' });
      if (refreshResponse.ok) {
        const session = await refreshResponse.json();
        setToken(session.access_token);
        response = await send(session.access_token);
      } else {
        setToken(''); setUser(null);
      }
    }
    const data = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data?.detail || `API ${response.status}`);
    return data;
  }, [token]);

  const refresh = useCallback(async () => {
    const [poiResult, contentResult, taskResult] = await Promise.all([api('/admin/pois'), api('/admin/contents'), api('/admin/tasks')]);
    setPois(poiResult.data || []); setContents(contentResult.data || []); setTasks(taskResult.data || []);
    if (user?.role === 'ADMIN') {
      const [auditResult, analyticsResult, userResult] = await Promise.all([api('/admin/audit'), api('/admin/analytics/summary'), api('/admin/users')]);
      setAudit(auditResult.data || []); setAnalytics(analyticsResult); setUsers(userResult.data || []);
    }
  }, [api, user]);

  useEffect(() => {
    let cancelled = false;
    localStorage.removeItem('q1-admin-token');
    fetch(`${API}/admin/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then(async (response) => response.ok ? response.json() : null)
      .then((session) => { if (!cancelled && session?.access_token) setToken(session.access_token); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);
  useEffect(() => { if (!token) return; api('/admin/auth/me').then(setUser).catch(() => { setToken(''); setUser(null); }); }, [api, token]);
  useEffect(() => { if (user) refresh().catch((error) => setMessage(error.message)); }, [user, refresh]);
  useEffect(() => { if (!user) return undefined; const timer = window.setInterval(() => refresh().catch(() => {}), 4000); return () => window.clearInterval(timer); }, [user, refresh]);

  const login = async (event) => {
    event.preventDefault(); setBusy(true); setMessage('');
    try { const result = await fetch(`${API}/admin/auth/login`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) }); const data = await result.json(); if (!result.ok) throw new Error(data.detail || 'Đăng nhập thất bại'); setToken(data.access_token); setUser(data.user); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  };
  const signOut = async () => {
    let serverLoggedOut = false;
    try { await api('/admin/auth/logout', { method: 'POST' }); serverLoggedOut = true; }
    catch { /* Clear the local session even if the API cannot be reached. */ }
    localStorage.removeItem('q1-admin-token'); setToken(''); setUser(null);
    setMessage(serverLoggedOut ? '' : 'Đã đăng xuất trên thiết bị; máy chủ chưa xác nhận thu hồi phiên.');
  };
  const notify = (text) => { setMessage(text); window.setTimeout(() => setMessage(''), 4500); };
  const changeForm = (key, value) => setPoiForm((form) => ({ ...form, [key]: value }));
  const selectPoi = (poi) => {
    setEditingId(poi.id); setPoiForm({ title: poi.title || '', title_en: poi.title_en || '', slug: poi.slug || '', category: poi.category || '', address: poi.address || '', opening_hours: poi.opening_hours || '', latitude: String(poi.location?.coordinates?.[1] ?? ''), longitude: String(poi.location?.coordinates?.[0] ?? ''), geofence_radius: String(poi.geofence_radius ?? 30), wikipedia_url: poi.source_ref?.url || '', summary_vi: poi.summary_vi || '', summary_en: poi.summary_en || '' });
  };
  const savePoi = async (event) => {
    event.preventDefault(); setBusy(true);
    const payload = { ...poiForm, latitude: Number(poiForm.latitude), longitude: Number(poiForm.longitude), geofence_radius: Number(poiForm.geofence_radius), wikipedia_url: poiForm.wikipedia_url || null };
    try { await api(editingId ? `/admin/pois/${editingId}` : '/admin/pois', { method: editingId ? 'PATCH' : 'POST', body: JSON.stringify(payload) }); setPoiForm(emptyPoi); setEditingId(null); await refresh(); notify('Đã lưu địa điểm'); }
    catch (error) { notify(error.message); }
    finally { setBusy(false); }
  };
  const generate = async (poiId) => { try { const result = await api(`/admin/pois/${poiId}/generate`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } }); notify(`Đã tạo tác vụ ${result.task_id.slice(0, 8)}`); await refresh(); watchTask(result.task_id); } catch (error) { notify(error.message); } };
  const review = async (content, approve) => {
    try {
      if (!approve) await api(`/admin/contents/${content.id}`, { method: 'PATCH', body: JSON.stringify({ script_vi: content._editText || content.script_vi, review_note: content.review_note || null }) });
      else await api(`/admin/contents/${content.id}/approve`, { method: 'POST' });
      await refresh(); notify(approve ? 'Đã duyệt nội dung' : 'Đã lưu bản biên tập');
    } catch (error) { notify(error.message); }
  };
  const saveLocalization = async (content) => { try { await api(`/admin/contents/${content.id}/localizations`, { method: 'PUT', body: JSON.stringify({ locale: 'en-US', script: localizationText }) }); setLocalizationId(null); setLocalizationText(''); await refresh(); notify('Đã lưu bản dịch tiếng Anh'); } catch (error) { notify(error.message); } };
  const runAudio = async (contentId) => { try { const result = await api(`/admin/contents/${contentId}/build-audio`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } }); notify(`Đã đưa tác vụ dịch và audio vào hàng chờ: ${result.task_id.slice(0, 8)}`); await refresh(); watchTask(result.task_id); } catch (error) { notify(error.message); } };
  const publish = async (contentId) => { try { await api(`/admin/contents/${contentId}/publish`, { method: 'POST' }); await refresh(); notify('Địa điểm đã xuất bản'); } catch (error) { notify(error.message); } };
  const unpublish = async (poiId) => { try { await api(`/admin/pois/${poiId}/unpublish`, { method: 'POST' }); await refresh(); notify('Đã gỡ xuất bản'); } catch (error) { notify(error.message); } };
  const removePoi = async (poiId) => { if (!window.confirm('Xóa địa điểm và nội dung liên quan?')) return; try { await api(`/admin/pois/${poiId}`, { method: 'DELETE' }); setEditingId(null); setPoiForm(emptyPoi); await refresh(); } catch (error) { notify(error.message); } };
  const createUser = async (event) => { event.preventDefault(); try { await api('/admin/users', { method: 'POST', body: JSON.stringify(newUser) }); setNewUser({ username: '', password: '', role: 'REVIEWER' }); await refresh(); notify('Đã tạo tài khoản'); } catch (error) { notify(error.message); } };
  const watchTask = useCallback(async (taskId) => {
    try {
      const response = await fetch(`${API}/admin/tasks/${taskId}/events`, { headers: { Authorization: `Bearer ${token}` }, credentials: 'include' });
      if (!response.ok || !response.body) return;
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true });
        let splitAt = buffer.indexOf('\n\n');
        while (splitAt >= 0) {
          const eventBlock = buffer.slice(0, splitAt); buffer = buffer.slice(splitAt + 2);
          const line = eventBlock.split('\n').find((item) => item.startsWith('data: '));
          if (line) { const task = JSON.parse(line.slice(6)); setTasks((current) => [task, ...current.filter((item) => item.id !== task.id)]); if (['COMPLETED', 'FAILED'].includes(task.status)) return; }
          splitAt = buffer.indexOf('\n\n');
        }
      }
    } catch { /* The periodic task refresh remains available if streaming disconnects. */ }
  }, [token]);

  if (!user) return <main className="admin-login-wrap"><button className="admin-back" onClick={onClose}>← Quay lại tham quan</button><form className="admin-login" onSubmit={login}><span className="eyebrow">QUẬN 1 TOURISM · ADMIN</span><h1>Quản trị nội dung</h1><p>Đăng nhập để quản lý địa điểm và quy trình thuyết minh.</p><label>Tên đăng nhập<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required /></label><label>Mật khẩu<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>{message && <div className="admin-message">{message}</div>}<button className="admin-primary" disabled={busy}>{busy ? 'Đang đăng nhập…' : 'Đăng nhập'}</button><small>Tài khoản demo cục bộ: admin / quan1-demo</small></form></main>;

  const tabs = [['pois', 'Địa điểm'], ['content', 'Duyệt nội dung'], ['tasks', 'Tác vụ'], ...(user.role === 'ADMIN' ? [['analytics', 'Phân tích'], ['users', 'Tài khoản'], ['audit', 'Nhật ký']] : [])];
  return <main className="admin-app"><header className="admin-top"><a className="brand" href="#admin"><span className="brand-mark">Q1</span><span><b>QUẬN 1</b><small>CONTENT ADMIN</small></span></a><div className="admin-account"><span>{user.username} · {user.role}</span><button onClick={signOut}>Đăng xuất</button><button onClick={onClose}>Thoát quản trị</button></div></header><section className="admin-heading"><div><span className="eyebrow">CONTENT WORKSPACE</span><h1>Bảng điều khiển</h1><p>Quản lý POI, kiểm duyệt nội dung và theo dõi tiến trình xử lý.</p></div><span className="admin-count">{pois.length.toString().padStart(2, '0')}<small>ĐỊA ĐIỂM</small></span></section>
    <nav className="admin-tabs">{tabs.map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</nav>
    {message && <div className="admin-toast" role="status">{message}<button onClick={() => setMessage('')}>×</button></div>}
    {tab === 'pois' && <div className="admin-category-quick-edit"><label>Danh mục<input maxLength="80" placeholder="Ví dụ: Di tích lịch sử" value={poiForm.category} onChange={(e) => changeForm('category', e.target.value)} /></label><label>Địa chỉ<input maxLength="300" placeholder="Địa chỉ khách có thể tìm đến" value={poiForm.address} onChange={(e) => changeForm('address', e.target.value)} /></label><label>Giờ mở cửa<input maxLength="300" placeholder="Ví dụ: 08:00–17:00, cập nhật theo nguồn chính thức" value={poiForm.opening_hours} onChange={(e) => changeForm('opening_hours', e.target.value)} /></label><small>Lưu cùng POI khi bấm “Tạo POI nháp” hoặc “Lưu thay đổi”.</small></div>}
    {tab === 'pois' && <div className="admin-columns"><section className="admin-card"><div className="admin-card-title"><h2>{editingId ? 'Chỉnh sửa địa điểm' : 'Thêm địa điểm'}</h2>{editingId && <button className="admin-text-button" onClick={() => { setEditingId(null); setPoiForm(emptyPoi); }}>Tạo mới</button>}</div><form className="admin-form" onSubmit={savePoi}><label>Tên địa điểm<input required value={poiForm.title} onChange={(e) => changeForm('title', e.target.value)} /></label><label>Tên tiếng Anh<input value={poiForm.title_en} onChange={(e) => changeForm('title_en', e.target.value)} /></label><label>Slug<input required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" value={poiForm.slug} onChange={(e) => changeForm('slug', e.target.value)} /></label><div className="admin-form-row"><label>Vĩ độ<input type="number" step="any" required value={poiForm.latitude} onChange={(e) => changeForm('latitude', e.target.value)} /></label><label>Kinh độ<input type="number" step="any" required value={poiForm.longitude} onChange={(e) => changeForm('longitude', e.target.value)} /></label></div><label>Bán kính geofence (m)<input type="number" min="1" max="1000" value={poiForm.geofence_radius} onChange={(e) => changeForm('geofence_radius', e.target.value)} /></label><label>URL bài Wikipedia<input type="url" placeholder="https://vi.wikipedia.org/wiki/..." value={poiForm.wikipedia_url} onChange={(e) => changeForm('wikipedia_url', e.target.value)} /></label><label>Tóm tắt tiếng Việt<textarea rows="3" value={poiForm.summary_vi} onChange={(e) => changeForm('summary_vi', e.target.value)} /></label><label>Tóm tắt tiếng Anh<textarea rows="3" value={poiForm.summary_en} onChange={(e) => changeForm('summary_en', e.target.value)} /></label><button className="admin-primary" disabled={busy}>{editingId ? 'Lưu thay đổi' : 'Tạo POI nháp'}</button></form></section><section className="admin-card"><div className="admin-card-title"><h2>Danh sách POI</h2><button className="admin-text-button" onClick={() => refresh()}>Làm mới ↻</button></div><div className="admin-list">{pois.map((poi) => <article className="admin-poi-row" key={poi.id}><button className="admin-poi-select" onClick={() => selectPoi(poi)}><b>{poi.title}</b><small>{poi.slug} · {poi.status} · {poi.geofence_radius} m</small><small>{poi.source_ref?.url || 'Chưa có nguồn Wikipedia'}</small></button><div className="admin-actions"><button onClick={() => generate(poi.id)} disabled={!poi.source_ref?.url}>Tạo bản nháp</button><button onClick={() => selectPoi(poi)}>Sửa</button><button onClick={() => unpublish(poi.id)}>Gỡ xuất bản</button><button className="danger" onClick={() => removePoi(poi.id)}>Xóa</button></div></article>)}</div></section></div>}
    {tab === 'content' && <section className="admin-card"><div className="admin-card-title"><h2>Bản nội dung</h2><button className="admin-text-button" onClick={refresh}>Làm mới ↻</button></div>{contents.length === 0 && <p className="admin-empty">Chưa có bản nháp. Cấu hình Wikipedia cho một POI rồi chọn “Tạo bản nháp”.</p>}{contents.map((content) => <article className="content-review" key={content.id}><div className="content-meta"><div><b>{pois.find((poi) => poi.id === content.poi_id)?.title || content.poi_id}</b><small>Phiên bản {content.version} · {content.status} · {content.ai_model || 'AI provider'}</small></div><span>{content.source_revision ? `Wikipedia revision ${content.source_revision}` : ''}</span></div>{content.status === 'IN_REVIEW' ? <><textarea defaultValue={content.script_vi} onChange={(e) => { content._editText = e.target.value; }} rows="7"/><label>Ghi chú duyệt<input value={content.review_note || ''} onChange={(e) => { content.review_note = e.target.value; }} placeholder="Ghi chú nội bộ" /></label><div className="admin-actions"><button onClick={() => review(content, false)}>Lưu chỉnh sửa</button><button className="admin-primary" onClick={() => review(content, true)}>Duyệt nội dung</button></div></> : <p className="content-preview">{content.script_vi}</p>}{['APPROVED', 'LOCALIZED'].includes(content.status) && <div className="localization-editor"><label>Bản dịch tiếng Anh<textarea rows="4" value={localizationId === content.id ? localizationText : content.script_en || ''} onFocus={() => { setLocalizationId(content.id); setLocalizationText(content.script_en || ''); }} onChange={(e) => setLocalizationText(e.target.value)} placeholder="Nhập bản dịch tiếng Anh đã được biên tập" /></label><div className="admin-actions"><button onClick={() => saveLocalization(content)}>Lưu bản dịch</button><button onClick={() => runAudio(content.id)}>Dịch tự động + tạo audio</button></div></div>}{content.status === 'AUDIO_READY' && <button className="admin-primary" onClick={() => publish(content.id)}>Xuất bản</button>}{content.status === 'PUBLISHED' && <span className="published-label">✓ Đã xuất bản</span>}</article>)}</section>}
    {tab === 'tasks' && <section className="admin-card"><div className="admin-card-title"><h2>Tác vụ nền</h2><span className="task-auto">Tự làm mới mỗi 4 giây</span></div>{tasks.length === 0 && <p className="admin-empty">Chưa có tác vụ nào.</p>}{tasks.map((task) => <article className="task-row" key={task.id}><div><b>{task.task_type}</b><small>{task.id} · POI {pois.find((poi) => poi.id === task.poi_id)?.title || task.poi_id}</small>{task.error_message && <small className="danger-text">{task.error_message}</small>}</div><span className={`task-state ${task.status.toLowerCase()}`}>{task.current_step} · {task.status}</span><small>{task.attempts}/{task.max_attempts} lần</small></article>)}</section>}
    {tab === 'analytics' && <section className="admin-card"><div className="admin-card-title"><h2>Analytics có consent</h2><button className="admin-text-button" onClick={refresh}>Làm mới ↻</button></div><div className="metric-grid"><article><small>TỔNG SỰ KIỆN</small><b>{analytics?.total_events ?? 0}</b></article>{Object.entries(analytics?.by_event_type || {}).map(([key, value]) => <article key={key}><small>{key.replaceAll('_', ' ').toUpperCase()}</small><b>{value}</b></article>)}</div><h3>POI được quan tâm</h3>{(analytics?.top_pois || []).map((row) => <p className="analytics-row" key={row.poi_id}>{pois.find((poi) => poi.id === row.poi_id)?.title || row.poi_id}<b>{row.events}</b></p>)}<p className="admin-empty">Không lưu tọa độ GPS. Sự kiện chỉ được ghi sau khi khách tham quan cấp consent.</p></section>}
    {tab === 'users' && user.role === 'ADMIN' && <div className="admin-columns"><section className="admin-card"><h2>Tạo tài khoản quản trị</h2><form className="admin-form" onSubmit={createUser}><label>Tên đăng nhập<input minLength="3" required value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} /></label><label>Mật khẩu (tối thiểu 12 ký tự)<input type="password" minLength="12" required value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} /></label><label>Vai trò<select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}><option value="REVIEWER">Reviewer</option><option value="ADMIN">Admin</option></select></label><button className="admin-primary">Tạo tài khoản</button></form></section><section className="admin-card"><h2>Tài khoản hiện có</h2>{users.map((item) => <p className="analytics-row" key={item.id}>{item.username}<b>{item.role} · {item.is_active ? 'active' : 'disabled'}</b></p>)}</section></div>}
    {tab === 'audit' && user.role === 'ADMIN' && <section className="admin-card"><div className="admin-card-title"><h2>Nhật ký hoạt động</h2><button className="admin-text-button" onClick={refresh}>Làm mới ↻</button></div>{audit.map((item) => <article className="task-row" key={item.id}><div><b>{{ 'auth.login.succeeded': 'Đăng nhập thành công', 'auth.login.failed': 'Đăng nhập thất bại', 'auth.logout': 'Đăng xuất' }[item.action] || item.action}</b><small>{item.details?.username || item.actor_id || 'Không xác định'} · {item.target_type} {item.target_id || ''}</small></div><time>{item.created_at ? new Date(item.created_at).toLocaleString('vi-VN') : ''}</time></article>)}</section>}
  </main>;
}
