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

  
  // --- SLIDESHOW OVERRIDE ---
  const DEMO_SLIDES = [
  {
    "summary": {
      "snapshot_date": "2026-04-30 14:00 UTC",
      "mrr_cents": 14200000,
      "mrr_d7_pct": 1.2,
      "nrr_pct": 104.2,
      "nrr_d7_delta": -1.4,
      "active_subs": 1240,
      "top_customer_share": 0.12,
      "failed_payments_cents": 450000,
      "failed_payments_count": 14,
      "series": [
        {
          "mrr_cents": 14000000
        },
        {
          "mrr_cents": 14100000
        },
        {
          "mrr_cents": 14200000
        }
      ]
    },
    "verdict": {
      "id": "v1",
      "rule": "churn_cluster",
      "priority": "P0",
      "confidence": "High",
      "resolved": false,
      "one_liner": "A concentrated churn cluster just appeared in your $500-$2k ARR segment.",
      "strategy_view": "A 3x churn spike in one segment is a positioning signal, not a retention problem.",
      "finance_view": "If this rate continues, you'll lose roughly one quarter's worth of NRR by month-end.",
      "tech_view": "Cross-reference cancellation events against the last 14 days of releases.",
      "contrarian_view": "Maybe this is healthy churn and you're shedding the wrong ICP. Accelerate it.",
      "evidence": {
        "ratio": 3.3
      },
      "actions": [
        "Pull churned customer list",
        "Pause non-critical pricing changes"
      ],
      "watch_metrics": [
        "Churn rate by ARR segment"
      ]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 14:15 UTC",
      "mrr_cents": 8900000,
      "mrr_d7_pct": -0.4,
      "nrr_pct": 98.1,
      "nrr_d7_delta": -2.1,
      "active_subs": 890,
      "top_customer_share": 0.25,
      "failed_payments_cents": 120000,
      "failed_payments_count": 4,
      "series": [
        {
          "mrr_cents": 9000000
        },
        {
          "mrr_cents": 8950000
        },
        {
          "mrr_cents": 8900000
        }
      ]
    },
    "verdict": {
      "id": "v2",
      "rule": "nrr_drop",
      "priority": "P1",
      "confidence": "Medium",
      "resolved": false,
      "one_liner": "NRR slipped below 100% for the first time in 6 months.",
      "strategy_view": "Your expansion engine stalled. Account management needs a new playbook.",
      "finance_view": "Below 100% NRR means you are now paying to replace revenue, destroying LTV/CAC.",
      "tech_view": "Look for usage drop-offs in the core feature set over the last 30 days.",
      "contrarian_view": "This is a natural normalization post-COVID. Don't panic, focus on new logos.",
      "evidence": {
        "current_nrr_pct": 98.1
      },
      "actions": [
        "Review top 10 downgrades",
        "Launch win-back campaign"
      ],
      "watch_metrics": [
        "Weekly active users in core features"
      ]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 14:30 UTC",
      "mrr_cents": 21500000,
      "mrr_d7_pct": 4.5,
      "nrr_pct": 112.5,
      "nrr_d7_delta": 2.5,
      "active_subs": 3100,
      "top_customer_share": 0.08,
      "failed_payments_cents": 850000,
      "failed_payments_count": 32,
      "series": [
        {
          "mrr_cents": 20500000
        },
        {
          "mrr_cents": 21000000
        },
        {
          "mrr_cents": 21500000
        }
      ]
    },
    "verdict": {
      "id": "v3",
      "rule": "failed_payment_leakage",
      "priority": "P0",
      "confidence": "High",
      "resolved": false,
      "one_liner": "Failed payments are up 4x this week, representing $8,500 of at-risk MRR.",
      "strategy_view": "This is silent churn. Dunning emails aren't enough; we need in-app gating.",
      "finance_view": "If we recover even 50%, we boost our net MRR growth by 2% this month.",
      "tech_view": "Stripe API might have declined a batch. Check the webhook logs for routing errors.",
      "contrarian_view": "Let the bad credit cards fail. Focus on enterprise clients who pay by invoice.",
      "evidence": {
        "avg_pct_of_mrr": 3.9
      },
      "actions": [
        "Trigger immediate dunning sequence",
        "Add in-app payment wall"
      ],
      "watch_metrics": [
        "Recovery rate over next 7 days"
      ]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 14:45 UTC",
      "mrr_cents": 5500000,
      "mrr_d7_pct": 8.1,
      "nrr_pct": 109.2,
      "nrr_d7_delta": 0.5,
      "active_subs": 420,
      "top_customer_share": 0.42,
      "failed_payments_cents": 15000,
      "failed_payments_count": 1,
      "series": [
        {
          "mrr_cents": 5100000
        },
        {
          "mrr_cents": 5300000
        },
        {
          "mrr_cents": 5500000
        }
      ]
    },
    "verdict": {
      "id": "v4",
      "rule": "concentration_risk",
      "priority": "P1",
      "confidence": "Medium",
      "resolved": false,
      "one_liner": "A single enterprise customer now makes up 42% of your total MRR.",
      "strategy_view": "You are essentially a consulting firm for this one client. Diversify immediately.",
      "finance_view": "If they churn, the runway gets cut in half. We cannot plan headcount on this.",
      "tech_view": "Ensure our architecture isn't becoming a bespoke monolith for their specific needs.",
      "contrarian_view": "Lean into it. Build exactly what they want and charge them double next year.",
      "evidence": {
        "top_share_pct": 42.0
      },
      "actions": [
        "Pause custom feature requests",
        "Ramp up SMB marketing spend"
      ],
      "watch_metrics": [
        "New logo acquisition rate"
      ]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 15:00 UTC",
      "mrr_cents": 42000000,
      "mrr_d7_pct": 0.2,
      "nrr_pct": 101.1,
      "nrr_d7_delta": -4.2,
      "active_subs": 8500,
      "top_customer_share": 0.03,
      "failed_payments_cents": 620000,
      "failed_payments_count": 28,
      "series": [
        {
          "mrr_cents": 41800000
        },
        {
          "mrr_cents": 41900000
        },
        {
          "mrr_cents": 42000000
        }
      ]
    },
    "verdict": {
      "id": "v5",
      "rule": "expansion_stall",
      "priority": "P2",
      "confidence": "Low",
      "resolved": false,
      "one_liner": "Seat expansion has flatlined across the mid-market cohort for 14 days.",
      "strategy_view": "The product is sticky, but not viral. We need a better multi-player loop.",
      "finance_view": "Without expansion, hitting our $10M ARR target requires 30% more top-of-funnel.",
      "tech_view": "Check if the invite-user flow is broken or experiencing high latency.",
      "contrarian_view": "They don't want to invite teammates. Stop forcing it and raise the base price.",
      "evidence": {
        "recent_avg_expansion_cents": 12000
      },
      "actions": [
        "Audit the invite-team UX",
        "Offer a limited-time seat discount"
      ],
      "watch_metrics": [
        "Invites sent per active user"
      ]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 15:15 UTC",
      "mrr_cents": 18400000,
      "mrr_d7_pct": -2.5,
      "nrr_pct": 94.8,
      "nrr_d7_delta": -3.8,
      "active_subs": 2100,
      "top_customer_share": 0.15,
      "failed_payments_cents": 310000,
      "failed_payments_count": 11,
      "series": [
        {
          "mrr_cents": 18800000
        },
        {
          "mrr_cents": 18600000
        },
        {
          "mrr_cents": 18400000
        }
      ]
    },
    "verdict": {
      "id": "v6",
      "rule": "pricing_tier_collapse",
      "priority": "P0",
      "confidence": "High",
      "resolved": false,
      "one_liner": "Pro tier subscriptions dropped 18% following the recent price hike.",
      "strategy_view": "We found the price ceiling. Roll back or add immediate grandfathered discounts.",
      "finance_view": "The elasticity is too high. The 20% price bump caused a net loss in ARR.",
      "tech_view": "Make sure the downgrade button isn't overly prominent in the new billing UI.",
      "contrarian_view": "Good. We shed the price-sensitive users who eat up all our support hours.",
      "evidence": {
        "tier": "Pro",
        "drop_pct": 18.2
      },
      "actions": [
        "Analyze support ticket volume from churned users",
        "Prepare a win-back offer"
      ],
      "watch_metrics": [
        "Downgrade rate next 7 days"
      ]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 15:30 UTC",
      "mrr_cents": 32000000,
      "mrr_d7_pct": 5.8,
      "nrr_pct": 118.2,
      "nrr_d7_delta": 4.1,
      "active_subs": 4200,
      "top_customer_share": 0.05,
      "failed_payments_cents": 550000,
      "failed_payments_count": 19,
      "series": [
        {
          "mrr_cents": 30000000
        },
        {
          "mrr_cents": 31000000
        },
        {
          "mrr_cents": 32000000
        }
      ]
    },
    "verdict": {
      "id": "v7",
      "rule": "churn_cluster",
      "priority": "P1",
      "confidence": "Medium",
      "resolved": false,
      "one_liner": "An unusual cluster of cancellations from EU customers in the past 48 hours.",
      "strategy_view": "A new competitor might have launched in Europe. Check Twitter and ProductHunt.",
      "finance_view": "EU is our fastest growing market. We need to plug this hole immediately.",
      "tech_view": "Our EU data center experienced a 15-minute outage on Tuesday. That is the trigger.",
      "contrarian_view": "It's August. Europe is on vacation. They are just pausing their accounts.",
      "evidence": {
        "ratio": 2.8
      },
      "actions": [
        "Check uptime logs for EU region",
        "Send a localized apology email if outage confirmed"
      ],
      "watch_metrics": [
        "EU cancellations vs US"
      ]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 15:45 UTC",
      "mrr_cents": 7800000,
      "mrr_d7_pct": 0.8,
      "nrr_pct": 105.1,
      "nrr_d7_delta": -0.5,
      "active_subs": 650,
      "top_customer_share": 0.18,
      "failed_payments_cents": 80000,
      "failed_payments_count": 3,
      "series": [
        {
          "mrr_cents": 7700000
        },
        {
          "mrr_cents": 7750000
        },
        {
          "mrr_cents": 7800000
        }
      ]
    },
    "verdict": {
      "id": "v8",
      "rule": "nrr_drop",
      "priority": "P2",
      "confidence": "Low",
      "resolved": false,
      "one_liner": "Expansion revenue from the SMB segment is softening.",
      "strategy_view": "SMBs are tightening budgets. We need to demonstrate hard ROI, not just convenience.",
      "finance_view": "CAC payback period is stretching from 6 months to 8 months for this cohort.",
      "tech_view": "They aren't hitting the usage limits that trigger upgrades. Check feature adoption.",
      "contrarian_view": "SMBs are a distraction anyway. Let it soften and move upmarket.",
      "evidence": {
        "current_nrr_pct": 105.1
      },
      "actions": [
        "Analyze usage patterns of SMBs",
        "Create an ROI case study"
      ],
      "watch_metrics": [
        "Time to upgrade for new SMBs"
      ]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 16:00 UTC",
      "mrr_cents": 51500000,
      "mrr_d7_pct": 12.4,
      "nrr_pct": 125.6,
      "nrr_d7_delta": 8.2,
      "active_subs": 12500,
      "top_customer_share": 0.02,
      "failed_payments_cents": 1250000,
      "failed_payments_count": 45,
      "series": [
        {
          "mrr_cents": 48000000
        },
        {
          "mrr_cents": 49500000
        },
        {
          "mrr_cents": 51500000
        }
      ]
    },
    "verdict": {
      "id": "v9",
      "rule": "failed_payment_leakage",
      "priority": "P1",
      "confidence": "High",
      "resolved": false,
      "one_liner": "Massive influx of new signups is bringing a high rate of fraudulent card failures.",
      "strategy_view": "Our marketing went viral, but we are attracting bad actors. Tighten the funnel.",
      "finance_view": "Stripe dispute fees will eat our margins if we don't block these at the gate.",
      "tech_view": "Enable Stripe Radar immediately and require 3D Secure for high-risk IP addresses.",
      "contrarian_view": "More top of funnel is always good. The algorithm will eventually sort them out.",
      "evidence": {
        "avg_pct_of_mrr": 2.4
      },
      "actions": [
        "Enable Stripe Radar rules",
        "Monitor dispute rates daily"
      ],
      "watch_metrics": [
        "Failed payments from new accounts"
      ]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 16:15 UTC",
      "mrr_cents": 12000000,
      "mrr_d7_pct": -5.2,
      "nrr_pct": 88.5,
      "nrr_d7_delta": -8.5,
      "active_subs": 1100,
      "top_customer_share": 0.35,
      "failed_payments_cents": 200000,
      "failed_payments_count": 8,
      "series": [
        {
          "mrr_cents": 12800000
        },
        {
          "mrr_cents": 12400000
        },
        {
          "mrr_cents": 12000000
        }
      ]
    },
    "verdict": {
      "id": "v10",
      "rule": "concentration_risk",
      "priority": "P0",
      "confidence": "High",
      "resolved": false,
      "one_liner": "Your second largest customer just cancelled, exposing dangerous concentration.",
      "strategy_view": "This is a red alert. Call the CEO of the churned account immediately.",
      "finance_view": "We just lost 15% of our MRR in a single day. Revise the quarterly forecast.",
      "tech_view": "Check if they exported their data before cancelling. Could indicate a move to a competitor.",
      "contrarian_view": "We were too dependent on them. Now we are forced to build a real business.",
      "evidence": {
        "top_share_pct": 35.0
      },
      "actions": [
        "Schedule post-mortem with the customer",
        "Audit features they used most"
      ],
      "watch_metrics": [
        "Health scores of remaining top 5 customers"
      ]
    }
  }
];
  
  let currentSlide = 0;
  let slideInterval = null;

  function cycleSlide() {
    const slide = DEMO_SLIDES[currentSlide];
    
    // Render snapshot and verdicts
    renderSnapshot({ today: slide.summary, deltas: slide.summary, series: slide.summary.series }, 'demo');
    renderVerdicts([slide.verdict]);
    renderCounters({ total_open: 1, by_priority: { [slide.verdict.priority]: 1 } });
    
    currentSlide = (currentSlide + 1) % DEMO_SLIDES.length;
  }

  async function runScan() {
    if (runBtn.disabled) return;
    runBtn.disabled = true;
    runLabel.textContent = 'Slideshow Active';
    runIcon.innerHTML = '<span class="ox-spinner" aria-hidden="true"></span>';
    
    cycleSlide();
    if (!slideInterval) {
      slideInterval = setInterval(cycleSlide, 6500);
    }
  }

  if (runBtn) runBtn.addEventListener('click', runScan);

  async function bootstrap() {
    await loadConnectors();
    runScan();
  }
  
  // --- AUDIT LOG STREAM ---
  const STREAM_EVENTS = [
    "Webhook: charge.succeeded [$140.00]",
    "Rule match: churn_cluster [skip]",
    "Anomaly scan: completed (124ms)",
    "Webhook: customer.subscription.deleted",
    "Verdict synthesized: P0 Churn",
    "DB Sync: active_subs (1240)",
    "Webhook: invoice.payment_failed",
    "Rule match: failed_payment_leakage",
    "Chairman verdict generated",
    "Data pipeline: 41 events processed",
    "Sync: Stripe -> Oracle (12ms)"
  ];
  const streamEl = document.getElementById('ox-stream-list');
  if (streamEl) {
    setInterval(() => {
      if (Math.random() > 0.6) return;
      const li = document.createElement('li');
      const time = new Date().toISOString().split('T')[1].slice(0,8);
      li.textContent = `[${time}] ${STREAM_EVENTS[Math.floor(Math.random() * STREAM_EVENTS.length)]}`;
      streamEl.appendChild(li);
      if (streamEl.children.length > 5) {
        streamEl.removeChild(streamEl.firstChild);
      }
    }, 800);
  }

  bootstrap();
})();
