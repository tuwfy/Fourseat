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
    engineering_velocity:    'Engineering velocity decline',
    sprint_scope_creep:      'Sprint scope creep',
    deploy_freeze_risk:      'Deploy freeze → churn risk',
    expense_anomaly:         'Expense anomaly',
    slack_sentiment_shift:   'Team sentiment shift',
    cross_source_misalign:   'Revenue ↔ engineering misalignment',
    ar_aging_risk:           'Accounts receivable aging',
    pr_bottleneck:           'PR review bottleneck',
    team_burnout_signal:     'Team burnout signal',
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
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = 'Encrypting & archiving...';
    await new Promise(r => setTimeout(r, 600));
    btn.textContent = '✓ Marked resolved';
    btn.style.background = 'rgba(63, 138, 100, 0.15)';
    btn.style.color = 'var(--finance)';
    btn.style.borderColor = 'rgba(63, 138, 100, 0.4)';
    flash('Verdict securely archived to the resolution log.');
    
    // Reset the interval and cycle to next slide
    setTimeout(() => {
      if (slideInterval) { clearInterval(slideInterval); slideInterval = setInterval(cycleSlide, 15000); }
      cycleSlide();
    }, 1500);
  }

  async function onGenerateDeck(verdict, btn) {
    btn.disabled = true;
    btn.textContent = 'Synthesizing narrative...';
    await new Promise(r => setTimeout(r, 800));
    btn.textContent = 'Generating slides...';
    await new Promise(r => setTimeout(r, 700));
    btn.textContent = '✓ Board deck ready';
    btn.style.background = 'rgba(183, 114, 66, 0.15)';
    btn.style.color = 'var(--accent)';
    btn.style.borderColor = 'rgba(183, 114, 66, 0.4)';
    flash('Board deck successfully generated. Ready for download.');
    
    // Show mini deck preview
    const ctaWrap = btn.closest('.ox-verdict-cta');
    const slideFrame = document.createElement('div');
    slideFrame.className = 'ox-deck-preview';
    slideFrame.style.marginTop = '1.5rem';
    slideFrame.style.border = '1px solid var(--line)';
    slideFrame.style.borderRadius = '8px';
    slideFrame.style.padding = '1.5rem';
    slideFrame.style.background = 'var(--bg)';
    slideFrame.style.boxShadow = '0 10px 30px rgba(0,0,0,0.1)';
    slideFrame.style.animation = 'oxRiseLeft 0.5s cubic-bezier(.2,.8,.2,1) both';
    
    // Build fake chart bars
    const bars = [];
    for(let i=0; i<8; i++){
       const h = 20 + Math.random()*60;
       const color = i === 7 ? 'var(--p0)' : 'var(--p1)';
       const opacity = i === 7 ? '1' : '0.4';
       bars.push(`<div style="width:100%; height:${h}%; background:${color}; opacity:${opacity}; border-radius:3px 3px 0 0; transition:height 1s cubic-bezier(.2,.8,.2,1);"></div>`);
    }

    slideFrame.innerHTML = `
      <div style="font-family:'Inter', sans-serif; text-align:left; display:flex; flex-direction:column; gap:1.2rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--line); padding-bottom:0.8rem;">
            <div style="font-size:0.65rem; color:var(--muted); text-transform:uppercase; font-weight:700; letter-spacing:0.1em;">Slide 1 of 6 &middot; Confidential</div>
            <div style="font-size:0.65rem; color:var(--accent); text-transform:uppercase; font-weight:700; letter-spacing:0.1em; background:rgba(232, 168, 124, 0.1); padding:2px 8px; border-radius:12px;">Auto-Generated</div>
        </div>
        
        <div>
            <div style="font-weight:400; font-size:1.8rem; color:var(--fg); margin-bottom:0.4rem; font-family:'Instrument Serif', serif; letter-spacing:-0.02em;">${ruleLabel(verdict.rule)}</div>
            <div style="font-size:0.85rem; color:var(--muted); line-height:1.5;">${verdict.one_liner}</div>
        </div>
        
        <div style="display:grid; grid-template-columns: 1fr 1.5fr; gap:1.5rem; margin-top:0.5rem;">
            <!-- Left: Stats -->
            <div style="display:flex; flex-direction:column; gap:1rem;">
                <div style="background:var(--card-tint); border:1px solid var(--line-2); border-radius:6px; padding:1rem;">
                    <div style="font-size:0.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">Est. Impact</div>
                    <div style="font-family:'Instrument Serif', serif; font-size:1.6rem; color:var(--p0); line-height:1;">$12,450 <span style="font-size:0.8rem; font-family:'Inter', sans-serif; color:var(--muted); font-weight:500;">/ mo</span></div>
                </div>
                <div style="background:var(--card-tint); border:1px solid var(--line-2); border-radius:6px; padding:1rem;">
                    <div style="font-size:0.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">AI Confidence</div>
                    <div style="font-size:1.2rem; font-weight:600; color:var(--fg); line-height:1;">94.2%</div>
                </div>
            </div>
            
            <!-- Right: Chart -->
            <div style="background:var(--card-tint); border:1px solid var(--line-2); border-radius:6px; padding:1rem; display:flex; flex-direction:column;">
                <div style="font-size:0.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:1rem;">Trend (Last 8 Weeks)</div>
                <div style="flex:1; display:flex; align-items:flex-end; gap:6px; padding-bottom:4px; border-bottom:1px solid var(--line-2); position:relative;">
                    <!-- Grid lines -->
                    <div style="position:absolute; top:25%; left:0; right:0; height:1px; background:var(--line); border-top:1px dashed var(--line); z-index:0;"></div>
                    <div style="position:absolute; top:50%; left:0; right:0; height:1px; background:var(--line); border-top:1px dashed var(--line); z-index:0;"></div>
                    <div style="position:absolute; top:75%; left:0; right:0; height:1px; background:var(--line); border-top:1px dashed var(--line); z-index:0;"></div>
                    <!-- Bars -->
                    <div style="display:flex; width:100%; height:100%; align-items:flex-end; gap:8px; z-index:1;">
                        ${bars.join('')}
                    </div>
                </div>
                <div style="display:flex; justify-content:space-between; margin-top:0.5rem; font-size:0.6rem; color:var(--muted);">
                    <span>W-8</span>
                    <span>W-4</span>
                    <span>Now</span>
                </div>
            </div>
        </div>
        
        <div style="margin-top:0.5rem; padding-top:1rem; border-top:1px solid var(--line); text-align:right;">
            <button class="ox-mini-btn primary" style="padding:0.4rem 1rem; border-radius:4px; font-size:0.75rem; cursor:pointer;">Download Full PDF Deck</button>
        </div>
      </div>
    `;
    ctaWrap.parentNode.appendChild(slideFrame);
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
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 15:30 UTC",
      "mrr_cents": 11800000,
      "mrr_d7_pct": 0.8,
      "nrr_pct": 103.1,
      "nrr_d7_delta": -0.3,
      "active_subs": 1180,
      "top_customer_share": 0.14,
      "failed_payments_cents": 89000,
      "failed_payments_count": 3,
      "series": [{"mrr_cents": 11600000},{"mrr_cents": 11700000},{"mrr_cents": 11800000}]
    },
    "verdict": {
      "id": "v11",
      "rule": "engineering_velocity",
      "priority": "P0",
      "confidence": "High",
      "resolved": false,
      "one_liner": "GitHub deploy frequency dropped 67% this week while Linear sprint velocity fell 38%.",
      "strategy_view": "Engineering is blocked. If this continues, the Q3 roadmap slides 4-6 weeks. Escalate now.",
      "finance_view": "Slower shipping means delayed revenue from the enterprise tier launch. Adjust the forecast.",
      "tech_view": "14 PRs are stuck in review. Two senior engineers are out and no one has merge authority. Fix the CODEOWNERS file.",
      "contrarian_view": "Maybe the team is doing the right thing — shipping slower to avoid breaking production. Check the incident log.",
      "evidence": {"deploy_freq_drop": 67, "velocity_drop": 38},
      "actions": ["Unblock PR review pipeline", "Reassign merge authority"],
      "watch_metrics": ["Deploy frequency (daily)", "PR cycle time"]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 15:45 UTC",
      "mrr_cents": 15600000,
      "mrr_d7_pct": 2.1,
      "nrr_pct": 107.4,
      "nrr_d7_delta": 1.2,
      "active_subs": 1340,
      "top_customer_share": 0.09,
      "failed_payments_cents": 210000,
      "failed_payments_count": 7,
      "series": [{"mrr_cents": 15200000},{"mrr_cents": 15400000},{"mrr_cents": 15600000}]
    },
    "verdict": {
      "id": "v12",
      "rule": "expense_anomaly",
      "priority": "P1",
      "confidence": "High",
      "resolved": false,
      "one_liner": "QuickBooks flagged $42k in unbudgeted SaaS spend this month — 3x the normal run rate.",
      "strategy_view": "This is tool sprawl. Every new tool fragments the workflow. Consolidate before it becomes cultural.",
      "finance_view": "At this burn rate, SaaS spend alone eats 18% of gross margin. Cap it or justify each line item.",
      "tech_view": "Most of the spend is duplicate tooling — three monitoring platforms and two CI/CD providers. Consolidate.",
      "contrarian_view": "Maybe the team is experimenting with better tools. Don't kill innovation with budget controls too early.",
      "evidence": {"monthly_saas": 42000, "normal_run_rate": 14000},
      "actions": ["Audit all active SaaS subscriptions", "Set up approval workflow for new tools"],
      "watch_metrics": ["Monthly SaaS spend vs. budget"]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 16:00 UTC",
      "mrr_cents": 9200000,
      "mrr_d7_pct": -1.8,
      "nrr_pct": 96.2,
      "nrr_d7_delta": -3.1,
      "active_subs": 920,
      "top_customer_share": 0.22,
      "failed_payments_cents": 340000,
      "failed_payments_count": 11,
      "series": [{"mrr_cents": 9500000},{"mrr_cents": 9350000},{"mrr_cents": 9200000}]
    },
    "verdict": {
      "id": "v13",
      "rule": "deploy_freeze_risk",
      "priority": "P0",
      "confidence": "High",
      "resolved": false,
      "one_liner": "GitHub shows zero deploys in 72 hours. Stripe churn spiked 4x in the same window. These are correlated.",
      "strategy_view": "Customers are churning because the product stopped improving. Ship something visible today.",
      "finance_view": "The 72-hour freeze has already cost us $14k in churned MRR. Every additional day compounds.",
      "tech_view": "A failed CI pipeline is blocking all merges. The fix is a one-line config change in the build file.",
      "contrarian_view": "Correlation is not causation. The churn may be seasonal. But fix the pipeline anyway.",
      "evidence": {"deploy_gap_hours": 72, "churn_spike": 4.0},
      "actions": ["Fix CI pipeline immediately", "Ship a customer-visible update within 24h"],
      "watch_metrics": ["Deploy frequency", "Churn rate (daily)"]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 16:15 UTC",
      "mrr_cents": 13400000,
      "mrr_d7_pct": 1.4,
      "nrr_pct": 105.8,
      "nrr_d7_delta": 0.6,
      "active_subs": 1290,
      "top_customer_share": 0.11,
      "failed_payments_cents": 67000,
      "failed_payments_count": 2,
      "series": [{"mrr_cents": 13100000},{"mrr_cents": 13250000},{"mrr_cents": 13400000}]
    },
    "verdict": {
      "id": "v14",
      "rule": "team_burnout_signal",
      "priority": "P1",
      "confidence": "Medium",
      "resolved": false,
      "one_liner": "Slack shows 12 mentions of 'burnout' and 'overworked' in eng channels this week. Linear shows 60-hour sprint loads.",
      "strategy_view": "This is a retention risk. If you lose a senior engineer now, the roadmap dies. Act before they resign.",
      "finance_view": "Replacing a senior engineer costs 6-9 months of salary. Prevention is 10x cheaper than replacement.",
      "tech_view": "Sprint loads are 40% above sustainable capacity. Cut scope on the current sprint immediately.",
      "contrarian_view": "People vent in Slack. Check 1:1 notes and actual attrition signals before sounding the alarm.",
      "evidence": {"burnout_mentions": 12, "sprint_load_hours": 60},
      "actions": ["Schedule skip-level 1:1s this week", "Reduce current sprint scope by 30%"],
      "watch_metrics": ["Slack sentiment (eng channels)", "Sprint load vs. capacity"]
    }
  },
  {
    "summary": {
      "snapshot_date": "2026-04-30 16:30 UTC",
      "mrr_cents": 18200000,
      "mrr_d7_pct": 3.5,
      "nrr_pct": 112.1,
      "nrr_d7_delta": 2.4,
      "active_subs": 1520,
      "top_customer_share": 0.07,
      "failed_payments_cents": 45000,
      "failed_payments_count": 1,
      "series": [{"mrr_cents": 17500000},{"mrr_cents": 17800000},{"mrr_cents": 18200000}]
    },
    "verdict": {
      "id": "v15",
      "rule": "cross_source_misalign",
      "priority": "P1",
      "confidence": "High",
      "resolved": false,
      "one_liner": "Revenue is up 3.5% but engineering is building features no paying customer requested. Linear backlog vs. Stripe expansion data are misaligned.",
      "strategy_view": "The product team is building what they think is cool, not what drives expansion. Realign the roadmap to top-revenue customer requests.",
      "finance_view": "Expansion revenue is coming from only 2 features. 80% of engineering effort is on features with zero revenue attribution.",
      "tech_view": "Cross-reference Linear tickets tagged 'customer-request' with actual Stripe expansion events. The overlap is only 12%.",
      "contrarian_view": "Some of the best products were built without customer input. But at this stage, you can't afford to guess.",
      "evidence": {"roadmap_customer_overlap": 12, "revenue_growth": 3.5},
      "actions": ["Tag all Linear tickets with revenue attribution", "Kill or pause non-revenue features"],
      "watch_metrics": ["Feature-to-revenue attribution rate"]
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
    runLabel.textContent = 'Scanning all sources';
    
    cycleSlide();
    if (!slideInterval) {
      slideInterval = setInterval(cycleSlide, 15000);
    }
    
    // Live timer
    let seconds = 0;
    const timerEl = document.getElementById('ox-live-timer');
    if (timerEl) {
      setInterval(() => {
        seconds++;
        const m = String(Math.floor(seconds / 60)).padStart(2, '0');
        const s = String(seconds % 60).padStart(2, '0');
        timerEl.textContent = m + ':' + s;
      }, 1000);
    }
  }

  // No click handler needed — indicator is display-only

  async function bootstrap() {
    await loadConnectors();
    runScan();
    initBrain();
  }

  // ── Company Brain UI ─────────────────────────────────────────────────────
  const BRAIN = {
    connectors: '/api/brain/connectors',
    scan:       '/api/brain/scan',
    query:      '/api/brain/query',
    signals:    '/api/brain/signals',
    resolve:    '/api/brain/signals/resolve',
  };

  const SOURCE_LABELS = {
    stripe:'Stripe', slack:'Slack', github:'GitHub',
    linear:'Linear', quickbooks:'QuickBooks', notion:'Notion',
  };

  async function loadBrainConnectors() {
    let live = {};
    let counts = {};
    try {
      const r = await fetchJSON(BRAIN.connectors);
      live = (r && r.connectors) || {};
      counts = (r && r.artifact_counts) || {};
    } catch (_e) {}
    // Stripe is configured at the Oracle level; fold its status in.
    let stripeLive = false;
    try {
      const r2 = await fetchJSON('/api/oracle/connectors');
      stripeLive = !!(r2 && r2.connectors && r2.connectors.stripe && r2.connectors.stripe.configured);
    } catch (_e) {}
    const nodes = document.querySelectorAll('.ox-bc');
    nodes.forEach(function (node) {
      const src = node.dataset.source;
      const meta = document.getElementById('ox-bc-meta-' + src);
      let isLive = false;
      if (src === 'stripe') isLive = stripeLive;
      else isLive = !!(live[src] && live[src].configured);
      const count = counts[src] || 0;
      node.classList.remove('is-live', 'is-demo');
      node.classList.add(isLive ? 'is-live' : 'is-demo');
      if (meta) {
        if (isLive) {
          meta.textContent = count > 0 ? (count + ' artifacts · live') : 'live';
        } else {
          meta.textContent = count > 0 ? (count + ' artifacts · preview') : 'preview';
        }
      }
    });
  }

  function renderSignal(sig) {
    const card = document.createElement('div');
    card.className = 'ox-signal' + (sig.resolved ? ' resolved' : '');
    const top = document.createElement('div');
    top.className = 'ox-signal-top';
    const pri = document.createElement('span');
    pri.className = 'ox-pri ' + (sig.priority || 'P2').toLowerCase();
    pri.textContent = sig.priority || 'P2';
    top.appendChild(pri);
    const rule = document.createElement('span');
    rule.className = 'ox-signal-rule';
    rule.textContent = (sig.rule || '').replace(/_/g, ' ');
    top.appendChild(rule);
    const conf = document.createElement('span');
    conf.className = 'ox-signal-conf ' + (sig.confidence || 'Medium').toLowerCase();
    conf.textContent = (sig.confidence || 'Medium') + ' confidence';
    top.appendChild(conf);
    card.appendChild(top);

    const headline = document.createElement('div');
    headline.className = 'ox-signal-headline';
    headline.textContent = sig.one_liner || '';
    card.appendChild(headline);

    const meta = document.createElement('div');
    meta.className = 'ox-signal-meta';
    meta.textContent = (sig.involved_artifact_ids || []).length + ' artifacts · ' +
                       (sig.detected_at || '').replace('T', ' ').slice(0, 16) + ' UTC';
    card.appendChild(meta);

    // Compact 4-advisor row
    const panel = document.createElement('div');
    panel.className = 'ox-panel';
    panel.style.marginTop = '.6rem';
    const advisors = [
      { role: 'Strategy', text: sig.strategy_view, c: '#9c5c2a' },
      { role: 'Finance', text: sig.finance_view, c: '#3f7a55' },
      { role: 'Technology', text: sig.tech_view, c: '#3a6dad' },
      { role: 'Contrarian', text: sig.contrarian_view, c: '#a83a22' },
    ];
    advisors.forEach(function (a) {
      const c = document.createElement('div');
      c.className = 'ox-panel-card';
      c.style.setProperty('--c', a.c);
      const r = document.createElement('div');
      r.className = 'ox-panel-role';
      r.textContent = a.role;
      const t = document.createElement('div');
      t.className = 'ox-panel-text';
      t.textContent = a.text || ('[' + a.role + ' offline]');
      c.appendChild(r);
      c.appendChild(t);
      panel.appendChild(c);
    });
    card.appendChild(panel);

    // Actions list
    if (sig.actions && sig.actions.length) {
      const ah = document.createElement('div');
      ah.className = 'ox-actions-head';
      ah.style.marginTop = '.8rem';
      ah.textContent = 'Recommended actions';
      card.appendChild(ah);
      const ul = document.createElement('ul');
      ul.className = 'ox-action-list';
      sig.actions.forEach(function (a) {
        const li = document.createElement('li');
        li.textContent = a;
        ul.appendChild(li);
      });
      card.appendChild(ul);
    }

    // CTA
    const cta = document.createElement('div');
    cta.className = 'ox-signal-actions';
    const resolve = document.createElement('button');
    resolve.type = 'button';
    resolve.className = 'ox-mini-btn';
    resolve.textContent = sig.resolved ? 'Re-open' : 'Mark resolved';
    resolve.addEventListener('click', async function () {
      resolve.disabled = true;
      try {
        await fetchJSON(BRAIN.resolve, {
          method: 'POST',
          body: JSON.stringify({ id: sig.id, resolved: !sig.resolved }),
        });
        await loadBrainSignals();
      } catch (e) {
        flash(e.message || 'Resolve failed', 'error');
        resolve.disabled = false;
      }
    });
    cta.appendChild(resolve);
    card.appendChild(cta);

    return card;
  }

  async function loadBrainSignals() {
    const wrap = document.getElementById('ox-brain-signals');
    if (!wrap) return;
    let signals = [];
    try {
      const r = await fetchJSON(BRAIN.signals + '?limit=10');
      signals = (r && r.signals) || [];
    } catch (_e) {}
    wrap.innerHTML = '';
    if (!signals.length) {
      const e = document.createElement('div');
      e.className = 'ox-empty';
      const h = document.createElement('h3');
      h.textContent = 'Brain is ready.';
      const p = document.createElement('p');
      p.textContent = 'Run a brain scan to detect cross-source signals across Slack, GitHub, Linear and Stripe.';
      e.appendChild(h); e.appendChild(p);
      wrap.appendChild(e);
      return;
    }
    signals.forEach(function (s) { wrap.appendChild(renderSignal(s)); });
  }

  async function runBrainScan() {
    const btn = document.getElementById('ox-brain-rescan');
    const original = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Scanning...'; }
    try {
      const data = await fetchJSON(BRAIN.scan, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      flash(
        (data.signals_detected || 0) + ' signal' +
        ((data.signals_detected === 1) ? '' : 's') +
        ' detected · ' + (data.mode || 'demo') + ' mode'
      );
      await loadBrainConnectors();
      await loadBrainSignals();
    } catch (e) {
      flash(e.message || 'Brain scan failed', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = original; }
    }
  }

  function renderAskResult(answer, citations) {
    const result = document.getElementById('ox-ask-result');
    const ans = document.getElementById('ox-ask-answer');
    const cites = document.getElementById('ox-ask-citations');
    if (!result || !ans || !cites) return;
    ans.textContent = answer || '';
    cites.innerHTML = '';
    (citations || []).forEach(function (c, i) {
      const a = document.createElement(c.url ? 'a' : 'div');
      a.className = 'ox-ask-cite';
      if (c.url) { a.href = c.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
      const num = document.createElement('span');
      num.className = 'ox-ask-cite-num';
      num.textContent = '[' + (i + 1) + ']';
      const body = document.createElement('div');
      body.textContent = c.title || '';
      const src = document.createElement('span');
      src.className = 'ox-ask-cite-source';
      src.textContent = SOURCE_LABELS[c.source] || c.source || '';
      a.appendChild(num); a.appendChild(body); a.appendChild(src);
      cites.appendChild(a);
    });
    result.hidden = false;
  }

  async function askBrain(question) {
    const btn = document.getElementById('ox-ask-btn');
    const input = document.getElementById('ox-ask-input');
    if (!question) return;
    if (btn) { btn.disabled = true; btn.textContent = '...'; }
    if (input) input.disabled = true;
    try {
      const data = await fetchJSON(BRAIN.query, {
        method: 'POST',
        body: JSON.stringify({ question: question }),
      });
      renderAskResult(data.answer || '', data.citations || []);
    } catch (e) {
      flash(e.message || 'Brain query failed', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Ask'; }
      if (input) input.disabled = false;
    }
  }

  function initBrain() {
    const form = document.getElementById('ox-ask-form');
    const input = document.getElementById('ox-ask-input');
    const rescan = document.getElementById('ox-brain-rescan');
    if (form) {
      form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        askBrain((input.value || '').trim());
      });
    }
    document.querySelectorAll('.ox-ask-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        const q = chip.dataset.q || '';
        if (input) input.value = q;
        askBrain(q);
      });
    });
    if (rescan) rescan.addEventListener('click', runBrainScan);
    loadBrainConnectors();
    // Auto-fire a brain scan on first load if no signals exist yet so the
    // demo dashboard never shows an empty state.
    fetchJSON(BRAIN.signals + '?limit=1').then(function (r) {
      if (!r || !r.signals || !r.signals.length) {
        runBrainScan();
      } else {
        loadBrainSignals();
      }
    }).catch(function () { runBrainScan(); });
  }
  
  // --- AUDIT LOG STREAM ---
  const STREAM_EVENTS = [
    "Stripe: charge.succeeded [$140.00]",
    "Stripe: customer.subscription.deleted",
    "Stripe: invoice.payment_failed [$89.00]",
    "QuickBooks: P&L sync completed (Q2)",
    "QuickBooks: expense anomaly flagged [$4,200 SaaS spend]",
    "QuickBooks: AR aging > 60 days for 3 accounts",
    "GitHub: PR #847 merged → main (auth-refactor)",
    "GitHub: deploy frequency: 3.2/day → 1.1/day (⚠ drop)",
    "GitHub: 14 PRs open > 5 days, review bottleneck detected",
    "Linear: Sprint velocity dropped 38% vs. last cycle",
    "Linear: 23 tickets moved to backlog (scope creep signal)",
    "Linear: Bug count up 4x in 'Payments' project",
    "Slack: #eng-general sentiment shift: neutral → negative",
    "Slack: 4 mentions of 'burnout' in last 48h",
    "Slack: CEO ↔ CTO DM frequency up 3x (escalation signal)",
    "Cross-source: churn spike correlates with deploy freeze",
    "Cross-source: Slack frustration + Linear backlog → team risk",
    "Chairman verdict synthesized: P0",
    "Pipeline: 147 events processed across 5 sources (89ms)",
    "Rule match: engineering_velocity_decline [triggered]",
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
