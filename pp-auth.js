// pp-auth.js

// read cookie by name
function getCookie(name) {
  return document.cookie.split('; ').find(r => r.startsWith(name + '='))?.split('=')[1];
}

// GET with credentials
async function apiGet(url) {
  const r = await fetch(url, { credentials: 'include' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// POST with credentials + CSRF
async function apiPost(url, body) {
  const csrf = getCookie('pp_csrf');
  const r = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body || {})
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// Guard for protected pages: redirects to login if no session
async function ensureSessionOrRedirect() {
  const r = await fetch('/api/session/me', { credentials: 'include' });
  if (!r.ok) {
    const next = location.pathname + location.search;
    location.replace('/login?next=' + encodeURIComponent(next));
    throw new Error('Not authenticated');
  }
  const me = await r.json();
  window.__ME__ = me;                 // уже есть
  window.PP_USER = me;                // удобно глобально
  document.documentElement.dataset.isAdmin = me.is_admin ? '1' : '0'; // флаг админа
  return me;
}


// Simple logout helper
async function logoutAndGoLogin() {
  try { await apiPost('/api/logout', {}); } catch {}
  location.href = '/login';
}
