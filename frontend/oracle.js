/* Fourseat Oracle - dashboard controller.
 * Pure browser JS, no inline scripts (CSP: script-src 'self').
 */
(function () {
  'use strict';

  const THEME_KEY = 'fourseat-theme';
  const ENDPOINTS = {
    connectors: '/api/oracle/connectors',
    scan:       '/api/oracle/scan',
    snapshot:   '/api/oracle/snapshot',
    verdicts:   '/api/oracle/verdicts',
    resolve:    '/api/oracle/resolve',
    deck:       '/api/oracle/deck',
  };

  // ── Theme (default to light per design intent) ───────────────────────────
  const themeToggle = document.getElementById('oracle-theme-toggle');

  function getPreferredTheme() {
    const saved = window.localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
    return 'light'; // Oracle defaults to light regardless of OS preference.
  }

  function applyTheme(theme) {
    const next = theme === 'dark' ? 'dark' : 'light';
    document.body.setAttribute('data-theme', next);
    document.documentElement.style.colorScheme = next;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', next === 'light' ? '#f6f2ea' : '#110f0d');
    if (themeToggle) {
      const label = themeToggle.querySelector('.theme-toggle-label');
      const goingTo = next === 'dark' ? 'light' : 'dark';
      themeToggle.setAttribute('aria-label', 'Switch to ' + goingTo + ' mode');
      themeToggle.setAttribute('aria-pressed', next === 'dark' ? 'true' : 'false');
      themeToggle.setAttribute('data-theme', next);
      if (label) label.textContent = next === 'dark' ? 'Dark' : 'Light';
    }
  }

  function toggleTheme() {
    const cur = document.body.getAttribute('data-theme') || 'light';
    const next = cur === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    window.localStorage.setItem(THEME_KEY, next);
  }

  if (themeToggle) themeToggle.addEventListener('click', toggleTheme);
  applyTheme(getPreferredTheme());

  // ── Helpers ──────────────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'class') node.className = attrs[k];
        else if (k === 'text') node.textContent = attrs[k];
        else if (k === 'html') node.innerHTML = attrs[k];
        else if (k === 'on' && typeof attrs[k] === 'object') {
          Object.keys(attrs[k]).forEach(function (ev) { node.addEventListener(ev, attrs[k][ev]); });
        } else if (k === 'style' && typeof attrs[k] === 'object') {
          Object.keys(attrs[k]).forEach(function (s) { node.style[s] = attrs[k][s]; });
        } else node.setAttribute(k, attrs[k]);
      });
    }
    if (children) {
      (Array.isArray(children) ? children : [children]).forEach(function (c) {
        if (c == null) return;
        node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
      });
    }
    return node;
  }

  function fmtMoney(cents) {
    if (cents == null || isNaN(cents)) return '--';
    const dollars = cents / 100;
    if (Math.abs(dollars) >= 1_000_000) return '$' + (dollars / 1_000_000).toFixed(2) + 'M';
    if (Math.abs(dollars) >= 1_000) return '$' + (dollars / 1_000).toFixed(1) + 'k';
    return '$' + dollars.toFixed(0);
  }

  // Count-up animation for metric values. Drives an interpolated scalar through
  // the formatter so the numbers tween up while the unit suffixes stay correct.
  function countUp(node, fromValue, toValue, fmt, duration) {
    if (!node) return;
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced || fromValue === toValue) {
      node.textContent = fmt(toValue);
      return;
    }
    const ms = duration || 900;
    const start = performance.now();
    const ease = function (t) { return 1 - Math.pow(1 - t, 3); };
    function frame(now) {
      const t = Math.min(1, (now - start) / ms);
      const v = fromValue + (toValue - fromValue) * ease(t);
      node.textContent = fmt(v);
      if (t < 1) requestAnimationFrame(frame);
      else {
        node.textContent = fmt(toValue);
        node.classList.add('flash');
        setTimeout(function () { node.classList.remove('flash'); }, 1200);
      }
    }
    requestAnimationFrame(frame);
  }
  // Track previous values so we tween from old → new on subsequent scans.
  const prevMetrics = { mrr: 0, nrr: 0, subs: 0, failed: 0 };
  function fmtPct(pct, digits) {
    if (pct == null || isNaN(pct)) return '--';
    return Number(pct).toFixed(digits == null ? 1 : digits) + '%';
  }
  function fmtSigned(pct) {
    if (pct == null || isNaN(pct)) return '--';
    const sign = pct > 0 ? '+' : '';
    return sign + Number(pct).toFixed(2) + '%';
  }

  function flash(text, kind) {
    const el = $('ox-flash');
    if (!el) return;
    el.classList.remove('show', 'error');
    if (!text) return;
    el.textContent = text;
    if (kind === 'error') el.classList.add('error');
    el.classList.add('show');
    if (kind !== 'error') {
      setTimeout(function () { el.classList.remove('show'); }, 4500);
    }
  }

  async function fetchJSON(url, opts) {
    const resp = await fetch(url, Object.assign({
      headers: { 'Content-Type': 'application/json' },
    }, opts || {}));
    let data = null;
    try { data = await resp.json(); } catch (_e) { data = null; }
    if (!resp.ok) {
      const err = (data && data.error) || ('Request failed: ' + resp.status);
      throw new Error(err);
    }
    return data;
  }

  // ── Connector status ─────────────────────────────────────────────────────
  // Single neutral pill: "Live · Stripe" when fully wired, "Workspace ready"
  // otherwise. We never expose env-var names or red error states to users.
  let stripeIsLive = false;
  async function loadConnectors() {
    const status = $('ox-stripe-status');
    const label  = $('ox-stripe-label');
    if (!status || !label) return;
    try {
      const data = await fetchJSON(ENDPOINTS.connectors);
      const s = (data && data.connectors && data.connectors.stripe) || {};
      status.classList.remove('ok', 'off');
      stripeIsLive = !!s.configured;
      if (s.configured && s.webhook_signed) {
        status.classList.add('ok');
        label.textContent = 'Live · Stripe';
      } else if (s.configured) {
        status.classList.add('ok');
        label.textContent = 'Live · Stripe (manual scans)';
      } else {
        label.textContent = 'Workspace ready';
      }
    } catch (_e) {
      label.textContent = 'Workspace ready';
    }
  }

  // ── Snapshot rendering ───────────────────────────────────────────────────
  function renderSnapshot(summary, mode) {
    if (!summary || !summary.today) return;
    const t = summary.today;
    const d = summary.deltas || {};

    $('ox-snapshot-date').textContent = t.snapshot_date || '';
    const tag = $('ox-snapshot-tag');
    if (tag) {
      if (mode === 'demo') {
        tag.hidden = false;
        tag.textContent = 'preview';
      } else {
        tag.hidden = false;
        tag.textContent = 'live';
        tag.classList.add('ox-tag-live');
      }
    }

    // Replace skeleton placeholders with the actual node before tweening.
    function clearSkeleton(node) {
      if (!node) return;
      const skel = node.querySelector('.ox-skel');
      if (skel) node.removeChild(skel);
    }
    ['ox-mrr', 'ox-nrr', 'ox-subs', 'ox-failed'].forEach(function (id) { clearSkeleton($(id)); });

    countUp($('ox-mrr'), prevMetrics.mrr, t.mrr_cents || 0, fmtMoney, 900);
    prevMetrics.mrr = t.mrr_cents || 0;

    const mrrDelta = d.mrr_d7_pct;
    const mrrDeltaEl = $('ox-mrr-delta');
    mrrDeltaEl.classList.remove('up', 'down');
    if (mrrDelta != null) {
      mrrDeltaEl.textContent = fmtSigned(mrrDelta) + ' vs 7d ago';
      mrrDeltaEl.classList.add(mrrDelta >= 0 ? 'up' : 'down');
    } else {
      mrrDeltaEl.textContent = 'vs 7d ago';
    }

    countUp($('ox-nrr'), prevMetrics.nrr, t.nrr_pct || 0, function (v) { return fmtPct(v, 1); }, 900);
    prevMetrics.nrr = t.nrr_pct || 0;

    const nrrDelta = d.nrr_d7_delta;
    const nrrDeltaEl = $('ox-nrr-delta');
    nrrDeltaEl.classList.remove('up', 'down');
    if (nrrDelta != null) {
      const sign = nrrDelta > 0 ? '+' : '';
      nrrDeltaEl.textContent = sign + Number(nrrDelta).toFixed(2) + 'pp vs 7d ago';
      nrrDeltaEl.classList.add(nrrDelta >= 0 ? 'up' : 'down');
    } else {
      nrrDeltaEl.textContent = 'vs 7d ago';
    }

    const subs = t.active_subs != null ? t.active_subs : 0;
    countUp($('ox-subs'), prevMetrics.subs, subs, function (v) { return Math.round(v).toLocaleString(); }, 900);
    prevMetrics.subs = subs;

    $('ox-top-share').textContent = (t.top_customer_share != null)
      ? 'top customer · ' + fmtPct(t.top_customer_share * 100, 1)
      : 'top customer share';

    countUp($('ox-failed'), prevMetrics.failed, t.failed_payments_cents || 0, fmtMoney, 900);
    prevMetrics.failed = t.failed_payments_cents || 0;
    $('ox-failed-count').textContent = (t.failed_payments_count || 0) + ' invoices today';

    renderSpark(summary.series || []);
  }

  function renderSpark(series) {
    const linePath = $('ox-spark-line');
    const fillPath = $('ox-spark-fill');
    if (!linePath || !fillPath) return;
    const W = 320, H = 80;
    if (!series || series.length < 2) {
      linePath.setAttribute('d', '');
      fillPath.setAttribute('d', '');
      return;
    }
    const values = series.map(function (s) { return Number(s.mrr_cents) || 0; });
    const minV = Math.min.apply(null, values);
    const maxV = Math.max.apply(null, values);
    const range = (maxV - minV) || 1;
    const stepX = W / (values.length - 1);
    const points = values.map(function (v, i) {
      const x = i * stepX;
      const y = H - ((v - minV) / range) * (H - 8) - 4;
      return [x, y];
    });
    const linePoints = points.map(function (p, i) {
      return (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ' ' + p[1].toFixed(1);
    }).join(' ');
    const fillPoints = linePoints + ' L' + W.toFixed(1) + ' ' + H + ' L0 ' + H + ' Z';
    linePath.setAttribute('d', linePoints);
    fillPath.setAttribute('d', fillPoints);
    // Trigger draw-in animation by toggling the class.
    linePath.classList.remove('draw');
    void linePath.getBBox();
    linePath.classList.add('draw');
  }

  // ── Counters ─────────────────────────────────────────────────────────────
  function renderCounters(stats) {
    const by = (stats && stats.by_priority) || {};
    $('ox-c-total').textContent = stats ? stats.total_open : 0;
    $('ox-c-p0').textContent = by.P0 || 0;
    $('ox-c-p1').textContent = by.P1 || 0;
    $('ox-c-p2').textContent = by.P2 || 0;
  }

  // ── Verdicts ─────────────────────────────────────────────────────────────
  const ADVISOR_COLORS = {
    Strategy:   '#b77242',
    Finance:    '#3f8a64',
    Technology: '#3a6dad',
    Contrarian: '#c0432c',
  };

  const RULE_LABELS = {
    churn_cluster:           'Churn cluster',
    nrr_drop:                'NRR drop',
    failed_payment_leakage:  'Failed payment leakage',
    concentration_risk:      'Concentration risk',
    expansion_stall:         'Expansion stall',
    pricing_tier_collapse:   'Pricing tier collapse',
  };

  function ruleLabel(rule) { return RULE_LABELS[rule] || rule; }

  function evidenceBlurb(verdict) {
    const ev = verdict.evidence || {};
    if (verdict.rule === 'churn_cluster' && ev.ratio != null) {
      return 'churn ' + Number(ev.ratio).toFixed(2) + 'x baseline';
    }
    if (verdict.rule === 'nrr_drop' && ev.current_nrr_pct != null) {
      return 'NRR ' + Number(ev.current_nrr_pct).toFixed(1) + '%';
    }
    if (verdict.rule === 'failed_payment_leakage' && ev.avg_pct_of_mrr != null) {
      return 'failed ' + Number(ev.avg_pct_of_mrr).toFixed(1) + '% of MRR';
    }
    if (verdict.rule === 'concentration_risk' && ev.top_share_pct != null) {
      return 'top customer ' + Number(ev.top_share_pct).toFixed(1) + '%';
    }
    if (verdict.rule === 'expansion_stall' && ev.recent_avg_expansion_cents != null) {
      return 'expansion ' + fmtMoney(ev.recent_avg_expansion_cents) + ' / day';
    }
    if (verdict.rule === 'pricing_tier_collapse' && ev.tier && ev.drop_pct != null) {
      return ev.tier + ' down ' + Number(ev.drop_pct).toFixed(0) + '%';
    }
    return 'evidence available';
  }

  function renderPanelCard(role, text) {
    const card = el('div', { class: 'ox-panel-card', style: { '--c': ADVISOR_COLORS[role] || '#b77242' } });
    card.style.setProperty('--c', ADVISOR_COLORS[role] || '#b77242');
    card.appendChild(el('div', { class: 'ox-panel-role', text: role }));
    card.appendChild(el('div', { class: 'ox-panel-text', text: text || '—' }));
    return card;
  }

  function renderVerdict(verdict) {
    const card = el('div', { class: 'ox-verdict' + (verdict.resolved ? ' resolved' : '') });

    // Top row: priority + rule + confidence
    const top = el('div', { class: 'ox-verdict-top' });
    top.appendChild(el('span', { class: 'ox-pri ' + (verdict.priority || 'P2').toLowerCase(), text: verdict.priority || 'P2' }));
    top.appendChild(el('span', { class: 'ox-rule', text: ruleLabel(verdict.rule) }));
    const conf = (verdict.confidence || 'Medium').toLowerCase();
    top.appendChild(el('span', { class: 'ox-conf ' + conf, text: (verdict.confidence || 'Medium') + ' confidence' }));
    card.appendChild(top);

    card.appendChild(el('div', { class: 'ox-headline', text: verdict.one_liner || '' }));
    card.appendChild(el('div', { class: 'ox-evidence', text: evidenceBlurb(verdict) }));

    // Advisor panel
    const panel = el('div', { class: 'ox-panel' });
    panel.appendChild(renderPanelCard('Strategy', verdict.strategy_view));
    panel.appendChild(renderPanelCard('Finance', verdict.finance_view));
    panel.appendChild(renderPanelCard('Technology', verdict.tech_view));
    panel.appendChild(renderPanelCard('Contrarian', verdict.contrarian_view));
    card.appendChild(panel);

    // Actions + watch
    const actionsWrap = el('div', { class: 'ox-actions' });
    actionsWrap.appendChild(el('div', { class: 'ox-actions-head', text: 'Recommended actions' }));
    const aList = el('ul', { class: 'ox-action-list' });
    (verdict.actions || []).forEach(function (a) { aList.appendChild(el('li', { text: a })); });
    actionsWrap.appendChild(aList);
    card.appendChild(actionsWrap);

    if (verdict.watch_metrics && verdict.watch_metrics.length) {
      const watchWrap = el('div', { class: 'ox-watch-row' });
      const wHead = el('div');
      wHead.appendChild(el('div', { class: 'ox-actions-head', text: 'Watch next week' }));
      const wList = el('ul', { class: 'ox-watch-list' });
      verdict.watch_metrics.forEach(function (m) { wList.appendChild(el('li', { text: m })); });
      wHead.appendChild(wList);
      watchWrap.appendChild(wHead);

      const evWrap = el('div');
      evWrap.appendChild(el('div', { class: 'ox-actions-head', text: 'Detected at' }));
      const detected = (verdict.detected_at || '').replace('T', ' ').slice(0, 16);
      evWrap.appendChild(el('div', { style: { fontFamily: 'JetBrains Mono, monospace', fontSize: '.85rem', color: 'var(--muted)' }, text: detected + ' UTC' }));
      watchWrap.appendChild(evWrap);
      card.appendChild(watchWrap);
    }

    // CTA row
    const cta = el('div', { class: 'ox-verdict-cta' });

    const deckBtn = el('button', {
      type: 'button',
      class: 'ox-mini-btn primary',
      on: { click: function () { onGenerateDeck(verdict, deckBtn); } },
    });
    deckBtn.appendChild(document.createTextNode(verdict.deck_filename ? 'Re-generate deck' : 'Generate board deck'));
    cta.appendChild(deckBtn);

    if (verdict.deck_filename) {
      cta.appendChild(el('a', {
        class: 'ox-mini-btn',
        href: '/api/brief/download/' + encodeURIComponent(verdict.deck_filename),
        text: 'Download .pptx',
      }));
    }

    const resolveBtn = el('button', {
      type: 'button',
      class: 'ox-mini-btn',
      on: { click: function () { onResolve(verdict, resolveBtn); } },
      text: verdict.resolved ? 'Re-open' : 'Mark resolved',
    });
    cta.appendChild(resolveBtn);

    card.appendChild(cta);
    return card;
  }

  function renderVerdicts(verdicts) {
    const wrap = $('ox-verdicts');
    wrap.innerHTML = '';
    if (!verdicts || !verdicts.length) {
      const empty = el('div', { class: 'ox-empty' });
      empty.appendChild(el('h3', { text: 'No active verdicts.' }));
      empty.appendChild(el('p', { text: 'Run a scan above. With demo data, you\'ll see anomalies fire immediately.' }));
      wrap.appendChild(empty);
      return;
    }
    verdicts.forEach(function (v) { wrap.appendChild(renderVerdict(v)); });
  }

  // ── Actions ──────────────────────────────────────────────────────────────
  async function onResolve(verdict, btn) {
    const wasResolved = !!verdict.resolved;
    btn.disabled = true;
    try {
      await fetchJSON(ENDPOINTS.resolve, {
        method: 'POST',
        body: JSON.stringify({ id: verdict.id, resolved: !wasResolved }),
      });
      flash(wasResolved ? 'Verdict re-opened.' : 'Verdict marked resolved.');
      await loadVerdicts();
    } catch (e) {
      flash(e.message || 'Resolve failed', 'error');
      btn.disabled = false;
    }
  }

  async function onGenerateDeck(verdict, btn) {
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Generating...';
    try {
      const data = await fetchJSON(ENDPOINTS.deck, {
        method: 'POST',
        body: JSON.stringify({ id: verdict.id }),
      });
      flash('Deck ready: ' + (data.filename || 'download below.'));
      await loadVerdicts();
    } catch (e) {
      flash(e.message || 'Deck generation failed', 'error');
      btn.disabled = false;
      btn.textContent = original;
    }
  }

  // ── Loaders ──────────────────────────────────────────────────────────────
  async function loadSnapshot() {
    try {
      const data = await fetchJSON(ENDPOINTS.snapshot + '?limit=60');
      if (data && data.summary && data.summary.count > 0) {
        renderSnapshot(data.summary, /* mode */ 'live');
      }
    } catch (_e) { /* silent on first load */ }
  }

  async function loadVerdicts() {
    try {
      const data = await fetchJSON(ENDPOINTS.verdicts + '?limit=20');
      renderVerdicts(data.verdicts || []);
      renderCounters(data.stats);
    } catch (e) {
      flash(e.message || 'Failed to load verdicts', 'error');
    }
  }

  // ── Run scan ─────────────────────────────────────────────────────────────
  const runBtn = $('ox-run-btn');
  const runLabel = $('ox-run-label');
  const runIcon = $('ox-run-icon');

  async function runScan() {
    if (runBtn.disabled) return;
    runBtn.disabled = true;
    const originalLabel = runLabel.textContent;
    runLabel.textContent = 'Running...';
    runIcon.innerHTML = '<span class="ox-spinner" aria-hidden="true"></span>';
    try {
      const data = await fetchJSON(ENDPOINTS.scan, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      const mode = (data && data.mode) || 'demo';
      if (data && data.summary) {
        renderSnapshot(data.summary, mode);
      }
      renderVerdicts(data.verdicts || []);
      renderCounters(data.stats);
      flash(
        (data.anomalies_detected || 0) + ' anomaly' + ((data.anomalies_detected === 1) ? '' : 'ies') +
        ' detected, ' + (data.verdicts_persisted || 0) + ' verdict' + ((data.verdicts_persisted === 1) ? '' : 's') +
        ' synthesized in ' + mode + ' mode.'
      );
    } catch (e) {
      flash(e.message || 'Scan failed', 'error');
    } finally {
      runBtn.disabled = false;
      runLabel.textContent = originalLabel;
      runIcon.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
    }
  }

  if (runBtn) runBtn.addEventListener('click', runScan);

  // ── Boot ─────────────────────────────────────────────────────────────────
  // Auto-scan on first load if no data exists yet, so the dashboard never
  // shows "--" placeholders. Subsequent loads reuse the persisted state.
  async function bootstrap() {
    await loadConnectors();
    let hasData = false;
    try {
      const snap = await fetchJSON(ENDPOINTS.snapshot + '?limit=60');
      if (snap && snap.summary && snap.summary.count > 0) {
        renderSnapshot(snap.summary, stripeIsLive ? 'live' : 'demo');
        hasData = true;
      }
    } catch (_e) {}
    try {
      const v = await fetchJSON(ENDPOINTS.verdicts + '?limit=20');
      if (v && v.verdicts && v.verdicts.length) {
        renderVerdicts(v.verdicts);
        renderCounters(v.stats);
        hasData = true;
      } else if (hasData) {
        renderVerdicts([]);
        renderCounters(v.stats);
      }
    } catch (_e) {}
    if (!hasData) {
      runScan();
    }
  }
  bootstrap();
})();
