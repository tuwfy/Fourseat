// Fourseat Sentinel - dashboard controller
// Reads /api/sentinel/queue, triggers /api/sentinel/run, resolves rows, and
// copies the rendered Markdown brief.

(function () {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    queue: [],
    stats: { total_open: 0, by_priority: { P0: 0, P1: 0, P2: 0, P3: 0 } },
    filter: 'all',
    openIds: new Set(),
    busy: false,
    lastSource: null,
  };

  const api = {
    async queue() {
      const r = await fetch('/api/sentinel/queue?limit=100');
      if (!r.ok) throw new Error('queue fetch failed');
      return r.json();
    },
    async run(limit = 10) {
      const r = await fetch('/api/sentinel/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit }),
      });
      if (!r.ok) throw new Error('run failed');
      return r.json();
    },
    async brief() {
      const r = await fetch('/api/sentinel/brief?limit=25');
      if (!r.ok) throw new Error('brief fetch failed');
      return r.json();
    },
    async resolve(id, resolved = true) {
      const r = await fetch('/api/sentinel/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, resolved }),
      });
      if (!r.ok) throw new Error('resolve failed');
      return r.json();
    },
  };

  function toast(msg, ms = 2200) {
    const el = $('#sx-toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove('show'), ms);
  }

  function setBusy(b) {
    state.busy = b;
    $('#sx-run').disabled = b;
    $('#sx-refresh').disabled = b;
  }

  function fmtWhen(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      const diff = (Date.now() - d.getTime()) / 1000;
      if (diff < 60) return 'just now';
      if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch (_e) {
      return iso;
    }
  }

  function esc(s) {
    return String(s || '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function prioClass(p) {
    return { P0: 'p0', P1: 'p1', P2: 'p2', P3: 'p3' }[p] || '';
  }

  function renderCounters() {
    $('#sx-c-total').textContent = state.stats.total_open;
    $('#sx-c-p0').textContent = state.stats.by_priority.P0 || 0;
    $('#sx-c-p1').textContent = state.stats.by_priority.P1 || 0;
    $('#sx-c-p2').textContent = state.stats.by_priority.P2 || 0;
    $('#sx-c-p3').textContent = state.stats.by_priority.P3 || 0;
  }

  function renderStatus() {
    const source = state.lastSource ? ` · source: ${state.lastSource}` : '';
    $('#sx-status').textContent = `${state.queue.length} items loaded${source}`;
    const sub = $('#sx-sub');
    if (!state.queue.length) {
      sub.textContent = 'No open items. Run Sentinel to triage your inbox.';
    } else {
      const top = state.queue[0];
      sub.textContent = `Top priority: ${top.priority} ${top.category} - ${top.one_liner || top.subject}`;
    }
  }

  function rowHtml(row, idx) {
    const p = prioClass(row.priority);
    const isOpen = state.openIds.has(row.id);
    const blind = (row.blind_spots || []).filter(Boolean);
    return `
      <tr data-id="${row.id}" class="${isOpen ? 'open' : ''}">
        <td>
          <button class="sx-row-toggle" data-toggle="${row.id}" aria-label="Toggle details">
            ${isOpen ? '\u2212' : '+'}
          </button>
        </td>
        <td><span class="sx-pill ${p}">${esc(row.priority)}</span></td>
        <td>${esc(row.category)}</td>
        <td><span class="sx-pill action">${esc(row.action)}</span></td>
        <td>
          <div class="sx-subject">${esc(row.subject)}</div>
          <div class="sx-oneliner">${esc(row.one_liner || '')}</div>
        </td>
        <td class="sx-sender" title="${esc(row.sender)}">${esc(row.sender)}</td>
        <td><span class="sx-pill conf-${esc(row.confidence)}">${esc(row.confidence)}</span></td>
        <td>
          <button class="sx-btn" data-resolve="${row.id}" style="padding:.35rem .75rem;font-size:.75rem">Done</button>
        </td>
      </tr>
      <tr class="sx-drawer ${isOpen ? 'open' : ''}" data-drawer="${row.id}">
        <td colspan="8">
          <div class="sx-panels">
            <div class="sx-panel"><h4>Strategy</h4><p>${esc(row.strategy_view) || '<span style="color:var(--dim)">no data</span>'}</p></div>
            <div class="sx-panel"><h4>Finance</h4><p>${esc(row.finance_view) || '<span style="color:var(--dim)">no data</span>'}</p></div>
            <div class="sx-panel"><h4>Technology</h4><p>${esc(row.tech_view) || '<span style="color:var(--dim)">no data</span>'}</p></div>
            <div class="sx-panel"><h4>Contrarian</h4><p>${esc(row.contrarian_view) || '<span style="color:var(--dim)">no data</span>'}</p></div>
          </div>
          ${blind.length ? `
            <div class="sx-blind">
              <h4>Memory blind spots</h4>
              <ul>${blind.map((b) => `<li>${esc(b)}</li>`).join('')}</ul>
            </div>
          ` : ''}
          <div class="sx-meta">
            <span>Received ${fmtWhen(row.received_at)}</span>
            <span>Processed ${fmtWhen(row.processed_at)}</span>
            <span>Source: ${esc(row.source)}</span>
            <span>ID #${row.id}</span>
          </div>
          ${row.reasoning ? `<div class="sx-meta"><span><strong style="color:var(--muted)">Why:</strong> ${esc(row.reasoning)}</span></div>` : ''}
        </td>
      </tr>
    `;
  }

  function renderTable() {
    const tbody = $('#sx-tbody');
    const filtered = state.filter === 'all'
      ? state.queue
      : state.queue.filter((r) => r.priority === state.filter);

    if (!filtered.length) {
      tbody.innerHTML = `
        <tr><td colspan="8" class="sx-empty">
          <div class="sx-orb"></div>
          <h3>${state.queue.length ? 'No items match this filter' : 'Queue is empty'}</h3>
          <p>${state.queue.length ? 'Try a different priority.' : 'Hit <strong>Run Sentinel</strong> to triage your inbox.'}</p>
        </td></tr>
      `;
      return;
    }

    tbody.innerHTML = filtered.map(rowHtml).join('');

    tbody.querySelectorAll('[data-toggle]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = Number(btn.dataset.toggle);
        if (state.openIds.has(id)) state.openIds.delete(id);
        else state.openIds.add(id);
        renderTable();
      });
    });
    tbody.querySelectorAll('[data-resolve]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = Number(btn.dataset.resolve);
        btn.disabled = true;
        try {
          await api.resolve(id, true);
          toast('Marked as resolved');
          await refresh();
        } catch (e) {
          toast('Could not resolve: ' + e.message);
          btn.disabled = false;
        }
      });
    });
  }

  async function refresh() {
    try {
      const data = await api.queue();
      state.queue = data.queue || [];
      state.stats = data.stats || state.stats;
      renderCounters();
      renderStatus();
      renderTable();
    } catch (e) {
      toast('Refresh failed: ' + e.message);
    }
  }

  async function run() {
    if (state.busy) return;
    setBusy(true);
    toast('Running Sentinel panel (this can take 30-60s)...', 3500);
    $('#sx-sub').textContent = 'Boardroom analyzing inbound messages...';
    try {
      const res = await api.run(10);
      state.lastSource = res.source;
      if (res.source === 'demo') $('#sx-banner').classList.add('show');
      else $('#sx-banner').classList.remove('show');
      toast(`Processed ${res.processed} new items (${res.fetched} fetched, ${res.source})`);
      await refresh();
    } catch (e) {
      toast('Run failed: ' + e.message);
    } finally {
      setBusy(false);
    }
  }

  async function copyMarkdown() {
    try {
      const data = await api.brief();
      await navigator.clipboard.writeText(data.markdown || '');
      toast('Markdown brief copied to clipboard');
    } catch (e) {
      toast('Copy failed: ' + e.message);
    }
  }

  function bindFilters() {
    $$('.sx-filter button').forEach((b) => {
      b.addEventListener('click', () => {
        $$('.sx-filter button').forEach((x) => x.classList.remove('on'));
        b.classList.add('on');
        state.filter = b.dataset.filter;
        renderTable();
      });
    });
  }

  function init() {
    bindFilters();
    $('#sx-run').addEventListener('click', run);
    $('#sx-refresh').addEventListener('click', refresh);
    $('#sx-markdown').addEventListener('click', copyMarkdown);
    refresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
