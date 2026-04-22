/* Fourseat admin dashboard.
 * Token is held in sessionStorage (default) or localStorage ("remember me").
 * All network calls go to /api/admin/* with Authorization: Bearer <token>.
 */

(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const STORAGE_KEY = 'fourseat.admin.token';

  const loginView = $('#login-view');
  const dashView = $('#dash-view');
  const loginForm = $('#login-form');
  const tokenInput = $('#token');
  const rememberInput = $('#remember');
  const loginErr = $('#login-err');
  const signoutBtn = $('#signout-btn');

  const statCount = $('#stat-count');
  const statLbl = $('#stat-lbl');
  const statMeta = $('#stat-meta');
  const rowsBody = $('#rows');
  const emptyNote = $('#empty');
  const refreshBtn = $('#refresh-btn');
  const csvBtn = $('#csv-btn');
  const copyBtn = $('#copy-btn');
  const toastEl = $('#toast');

  function readStoredToken() {
    try {
      return sessionStorage.getItem(STORAGE_KEY) || localStorage.getItem(STORAGE_KEY) || '';
    } catch (_) { return ''; }
  }

  function storeToken(token, persist) {
    try {
      (persist ? localStorage : sessionStorage).setItem(STORAGE_KEY, token);
      (persist ? sessionStorage : localStorage).removeItem(STORAGE_KEY);
    } catch (_) {}
  }

  function clearToken() {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(STORAGE_KEY);
    } catch (_) {}
  }

  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(() => toastEl.classList.remove('show'), 2200);
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatDate(iso) {
    if (!iso) return '-';
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleString(undefined, {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: '2-digit'
      });
    } catch (_) { return iso; }
  }

  async function fetchWaitlist(token) {
    const res = await fetch('/api/admin/waitlist?limit=1000', {
      headers: { 'Authorization': 'Bearer ' + token },
      cache: 'no-store'
    });
    if (res.status === 401) { const e = new Error('unauthorized'); e.code = 401; throw e; }
    if (res.status === 503) { const e = new Error('admin not configured'); e.code = 503; throw e; }
    if (!res.ok) throw new Error('request failed: ' + res.status);
    return res.json();
  }

  function renderMeta(data) {
    const items = [
      { label: 'Email', ok: !!data.email_configured },
      { label: 'Resend', ok: !!data.resend_configured },
      { label: 'SMTP', ok: !!data.smtp_configured },
      { label: 'Owner email', ok: !!data.owner_email_configured },
      { label: 'Blob mirror', ok: !!data.blob_configured }
    ];
    statMeta.innerHTML = items.map(i =>
      `<span><span class="admin-dot${i.ok ? '' : ' off'}"></span>${escapeHtml(i.label)} ${i.ok ? 'on' : 'off'}</span>`
    ).join('');
  }

  function renderRows(entries) {
    if (!entries || entries.length === 0) {
      rowsBody.innerHTML = '';
      emptyNote.style.display = 'block';
      return;
    }
    emptyNote.style.display = 'none';
    rowsBody.innerHTML = entries.map(e => `
      <tr>
        <td>${escapeHtml(formatDate(e.created_at))}</td>
        <td class="email"><a href="mailto:${escapeHtml(e.email)}">${escapeHtml(e.email)}</a></td>
        <td>${escapeHtml(e.name || '')}</td>
        <td>${escapeHtml(e.company || '')}</td>
      </tr>
    `).join('');
  }

  async function loadDashboard() {
    const token = readStoredToken();
    if (!token) { showLogin(); return; }
    try {
      statCount.textContent = '…';
      statLbl.textContent = 'loading';
      const data = await fetchWaitlist(token);
      statCount.textContent = String(data.count || 0);
      statLbl.textContent = (data.count === 1 ? 'signup' : 'signups');
      renderMeta(data);
      renderRows(data.entries || []);
      csvBtn.href = '/api/admin/waitlist.csv?token=' + encodeURIComponent(token);
      showDashboard();
    } catch (err) {
      if (err.code === 401) {
        clearToken();
        showLogin('Token rejected. Sign in again.');
      } else if (err.code === 503) {
        showLogin('Admin is not configured. Set FOURSEAT_ADMIN_TOKEN in your Vercel environment.');
      } else {
        toast('Could not load waitlist');
      }
    }
  }

  function showLogin(msg) {
    loginView.style.display = '';
    dashView.style.display = 'none';
    signoutBtn.style.display = 'none';
    loginErr.textContent = msg || '';
    setTimeout(() => { try { tokenInput.focus(); } catch (_) {} }, 50);
  }

  function showDashboard() {
    loginView.style.display = 'none';
    dashView.style.display = '';
    signoutBtn.style.display = '';
  }

  loginForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const token = (tokenInput.value || '').trim();
    if (!token) { loginErr.textContent = 'Enter a token.'; return; }
    try {
      loginErr.textContent = '';
      const data = await fetchWaitlist(token);
      storeToken(token, rememberInput.checked);
      statCount.textContent = String(data.count || 0);
      statLbl.textContent = (data.count === 1 ? 'signup' : 'signups');
      renderMeta(data);
      renderRows(data.entries || []);
      csvBtn.href = '/api/admin/waitlist.csv?token=' + encodeURIComponent(token);
      showDashboard();
      toast('Signed in');
    } catch (err) {
      if (err.code === 401) loginErr.textContent = 'Invalid token.';
      else if (err.code === 503) loginErr.textContent = 'Admin is not configured on the server.';
      else loginErr.textContent = 'Something went wrong. Try again.';
    }
  });

  refreshBtn.addEventListener('click', loadDashboard);

  signoutBtn.addEventListener('click', () => {
    clearToken();
    tokenInput.value = '';
    showLogin('Signed out.');
    toast('Signed out');
  });

  copyBtn.addEventListener('click', async () => {
    const token = readStoredToken();
    if (!token) return;
    try {
      const data = await fetchWaitlist(token);
      const emails = (data.entries || []).map(e => e.email).filter(Boolean).join(', ');
      if (!emails) { toast('No emails yet'); return; }
      await navigator.clipboard.writeText(emails);
      toast(`Copied ${data.entries.length} email${data.entries.length === 1 ? '' : 's'}`);
    } catch (_) {
      toast('Copy failed');
    }
  });

  loadDashboard();
})();
