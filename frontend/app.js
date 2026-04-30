/* Fourseat · frontend behavior
 * No inline event handlers, no eval, no innerHTML for untrusted data.
 */
(function () {
  'use strict';

  const API = '';
  const THEME_KEY = 'fourseat-theme';
  const PAGE_PATHS = {
    home: '/',
    how: '/how',
    pricing: '/pricing',
    about: '/about',
    waitlist: '/waitlist',
    terms: '/terms',
    privacy: '/privacy',
  };

  const COLORS = {
    claude: '#e8a87c',
    gpt4: '#7ccea8',
    gemini: '#7ca8e8',
    contrarian: '#e87c7c',
  };

  const MEMBER_DEFAULTS = {
    claude: { role: 'Chief Strategy Officer', ai: 'Strategy Engine' },
    gpt4: { role: 'Chief Financial Officer', ai: 'Finance Engine' },
    gemini: { role: 'Chief Technology Officer', ai: 'Technology Engine' },
    contrarian: { role: 'Independent Contrarian', ai: 'Contrarian Engine' },
  };

  const METRICS = [
    { l: 'Monthly Revenue', p: '$125,000' },
    { l: 'MRR Growth', p: '+18%' },
    { l: 'Total Customers', p: '342' },
    { l: 'Churn Rate', p: '2.1%' },
  ];

  const PHRASES = [
    'pressure-tests every decision.',
    'drafts board-ready decks.',
    'recalls every memo and update.',
    'turns metrics into a clear narrative.',
    'surfaces risks before you commit.',
  ];

  // ─── Helpers ────────────────────────────────────────────────────────────
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function toast(msg, type) {
    const t = $('#toast');
    if (!t) return;
    t.textContent = msg;
    t.className = 'toast ' + (type || 'ok') + ' show';
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { t.classList.remove('show'); }, 3200);
  }

  function setText(el, text) {
    if (!el) return;
    el.textContent = text == null ? '' : String(text);
  }

  function getPreferredTheme() {
    const saved = window.localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
    return 'light';
  }

  function applyTheme(theme) {
    const nextTheme = (theme === 'light') ? 'light' : 'dark';
    document.body.setAttribute('data-theme', nextTheme);
    document.documentElement.style.colorScheme = nextTheme;

    const metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) metaTheme.setAttribute('content', nextTheme === 'light' ? '#f6f2ea' : '#110f0d');

    $$('[data-theme-toggle]').forEach(function (btn) {
      const label = btn.querySelector('.theme-toggle-label');
      const goingTo = nextTheme === 'dark' ? 'light' : 'dark';
      btn.setAttribute('aria-label', 'Switch to ' + goingTo + ' mode');
      btn.setAttribute('aria-pressed', nextTheme === 'dark' ? 'true' : 'false');
      btn.setAttribute('data-theme', nextTheme);
      if (label) label.textContent = nextTheme === 'dark' ? 'Dark' : 'Light';
    });
  }

  function toggleTheme() {
    const current = document.body.getAttribute('data-theme') || getPreferredTheme();
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    window.localStorage.setItem(THEME_KEY, next);
  }

  function clearChildren(el) {
    if (!el) return;
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'class') node.className = attrs[k];
        else if (k === 'style') node.setAttribute('style', attrs[k]);
        else if (k === 'dataset') {
          Object.keys(attrs[k]).forEach(function (dk) { node.dataset[dk] = attrs[k][dk]; });
        } else node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) {
      if (c == null) return;
      if (typeof c === 'string') node.appendChild(document.createTextNode(c));
      else node.appendChild(c);
    });
    return node;
  }

  // ─── Page navigation ────────────────────────────────────────────────────
  function showPage(id) {
    $$('.page').forEach(function (p) { p.classList.remove('active'); });
    const target = document.getElementById('page-' + id);
    if (target) target.classList.add('active');
    $$('.nav-link[data-page]').forEach(function (b) { b.classList.remove('active'); });
    const activeBtn = document.querySelector('.nav-link[data-page="' + id + '"]');
    if (activeBtn) activeBtn.classList.add('active');
    // Keep URL path aligned with the active page for crawlability and sharing.
    if (history && history.replaceState) {
      try {
        const nextPath = PAGE_PATHS[id] || '/';
        history.replaceState(null, '', nextPath + window.location.search);
      } catch (_e) { /* noop */ }
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
    closeMobileNav();
    if (id === 'memory') loadDocs();
    if (id === 'waitlist') loadWaitlistCount();
  }

  async function loadWaitlistCount() {
    const el = $('#waitlist-count');
    if (!el) return;
    try {
      const r = await fetch(API + '/api/waitlist/count');
      if (!r.ok) return;
      const data = await r.json();
      const n = Number(data && data.count) || 0;
      if (n > 0) {
        const label = n === 1 ? 'founder has' : 'founders have';
        clearChildren(el);
        el.appendChild(elmStrong(n.toLocaleString()));
        el.appendChild(document.createTextNode(' ' + label + ' already joined'));
      } else {
        el.textContent = 'Be one of the first to join';
      }
    } catch (_e) { /* offline: leave blank */ }
  }

  function elmStrong(text) {
    return el('strong', {}, [text]);
  }

  function closeMobileNav() {
    const nav = $('nav');
    if (!nav) return;
    nav.classList.remove('open');
    const toggle = $('#nav-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
  }

  function toggleMobileNav() {
    const nav = $('nav');
    if (!nav) return;
    const open = nav.classList.toggle('open');
    const toggle = $('#nav-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  // ─── Waitlist + checkout ────────────────────────────────────────────────
  async function startSignup() {
    const email = ($('#waitlist-email') || {}).value || '';
    const name = ($('#waitlist-name') || {}).value || '';
    const company = ($('#waitlist-company') || {}).value || '';
    const cleanEmail = email.trim();
    const cleanName = name.trim();
    const cleanCompany = company.trim();
    const btn = $('#signup-btn');

    if (!cleanEmail) { toast('Please enter an email', 'err'); return; }

    if (btn) btn.disabled = true;
    try {
      const waitlistRes = await fetch(API + '/api/waitlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: cleanEmail, name: cleanName, company: cleanCompany }),
      });
      const waitlistData = await waitlistRes.json().catch(function () { return {}; });
      if (!waitlistRes.ok) {
        toast(waitlistData.error || 'Unable to join waitlist', 'err');
        return;
      }

      loadWaitlistCount();
      const pos = waitlistData.public_total || waitlistData.total;
      const posMsg = waitlistData.already_existed
        ? "You're already on the list. We'll be in touch."
        : (pos
          ? "You're in. You're #" + pos + " on the list."
          : "You're on the list. Check your inbox.");
      toast(posMsg, 'ok');

      const checkoutRes = await fetch(API + '/api/billing/checkout-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: cleanEmail, name: cleanName }),
      });
      const checkoutData = await checkoutRes.json().catch(function () { return {}; });
      if (!checkoutRes.ok) {
        toast(checkoutData.error || 'Unable to start checkout', 'err');
        return;
      }
      if (checkoutData.checkout_url) {
        window.location.assign(checkoutData.checkout_url);
        return;
      }
      if (checkoutData.success && checkoutData.billing_available === false) {
        toast(checkoutData.message || "You're on the list. We'll email you next steps.", 'ok');
        return;
      }
      toast('Checkout link was not returned', 'err');
    } catch (e) {
      toast('Unable to process signup right now', 'err');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ─── Debate engine ──────────────────────────────────────────────────────
  async function runDebate() {
    const q = ($('#debate-q') || {}).value || '';
    const ctx = ($('#debate-ctx') || {}).value || '';
    const question = q.trim();
    const context = ctx.trim();
    if (!question) { toast('Please enter a question', 'err'); return; }

    const btn = $('#debate-btn');
    if (btn) btn.disabled = true;
    const out = $('#debate-out');
    if (out) out.style.display = 'none';
    const L = $('#debate-loading');
    if (L) L.classList.add('active');

    let si = 0;
    const stepIds = ['s1', 's2', 's3'];
    stepIds.forEach(function (s) { const e = document.getElementById(s); if (e) e.className = 'step'; });
    const first = document.getElementById('s1');
    if (first) first.className = 'step now';
    const iv = setInterval(function () {
      if (si < stepIds.length - 1) {
        const cur = document.getElementById(stepIds[si]);
        if (cur) cur.className = 'step done';
        si++;
        const next = document.getElementById(stepIds[si]);
        if (next) next.className = 'step now';
      }
    }, 6000);

    try {
      const res = await fetch(API + '/api/debate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question, context: context }),
      });
      const data = await res.json().catch(function () { return {}; });
      clearInterval(iv);
      stepIds.forEach(function (s) { const e = document.getElementById(s); if (e) e.className = 'step done'; });
      if (!res.ok) {
        toast(data.error || 'The board could not be convened right now', 'err');
        return;
      }
      renderDebate(data);
    } catch (e) {
      clearInterval(iv);
      toast('Network issue. Please try again.', 'err');
    } finally {
      if (L) L.classList.remove('active');
      if (btn) btn.disabled = false;
    }
  }

  function memberCard(key, text, round, personas) {
    const m = (personas && personas[key]) || MEMBER_DEFAULTS[key] || { role: key, ai: '' };
    const c = COLORS[key] || '#e8ba83';
    const card = el('div', { class: 'board-card reveal active' }, [
      el('div', { class: 'board-card-bar', style: 'background:' + c }),
      el('div', { class: 'board-card-header' }, [
        el('div', {}, [el('div', { class: 'member-name' }, [m.role || ''])]),
        el('div', { class: 'ai-badge' }, [m.ai || '']),
      ]),
      el('div', { class: 'round-tag' }, [round]),
      el('div', { class: 'board-response' }, [text || '']),
    ]);
    return card;
  }

  function renderDebate(data) {
    const personas = data.personas || MEMBER_DEFAULTS;
    const leader = data.leader_name || 'Board Chair';
    const r1 = $('#r1');
    const r2 = $('#r2');
    clearChildren(r1);
    clearChildren(r2);
    ['claude', 'gpt4', 'gemini', 'contrarian'].forEach(function (k) {
      if (data.round1 && data.round1[k] && r1) {
        r1.appendChild(memberCard(k, data.round1[k], 'Independent response', personas));
      }
      if (data.round2 && data.round2[k] && r2) {
        r2.appendChild(memberCard(k, data.round2[k], 'Debating peers', personas));
      }
    });

    const c = data.chairman || {};
    const confidence = (c.confidence || 'High') + ' confidence';
    const confClass = ({
      high: 'conf-high', medium: 'conf-med', low: 'conf-low',
    })[(c.confidence || 'high').toString().toLowerCase()] || 'conf-high';

    const chairman = $('#chairman');
    clearChildren(chairman);

    chairman.appendChild(
      el('div', { class: 'chairman-hdr' }, [
        el('div', { class: 'chairman-orb' }),
        el('div', {}, [
          el('div', { class: 'chairman-title' }, [leader + ' · final decision']),
          el('div', { class: 'chairman-sub' }, ['Synthesis of the full debate']),
        ]),
      ])
    );

    chairman.appendChild(
      el('div', { class: 'verdict-box' }, [
        el('div', { class: 'verdict-text' }, [
          (c.verdict || 'Consensus reached.') + ' ',
          el('span', { class: 'conf-pill ' + confClass }, [confidence]),
        ]),
      ])
    );

    function listCol(title, items) {
      return el('div', { class: 'ch-col' }, [
        el('div', { class: 'ch-col-title' }, [title]),
        el('ul', { class: 'ch-list' },
          (items || []).map(function (item) { return el('li', {}, [String(item)]); })
        ),
      ]);
    }

    chairman.appendChild(el('div', { class: 'ch-grid' }, [
      listCol('Key risks', c.key_risks || []),
      listCol('Opportunities', c.key_opportunities || []),
      listCol('Action steps', c.action_steps || []),
    ]));

    const out = $('#debate-out');
    if (out) out.style.display = 'block';
  }

  // ─── Memory engine ──────────────────────────────────────────────────────
  async function uploadDoc(input) {
    if (!input || !input.files || !input.files[0]) return;
    const f = input.files[0];

    const allowed = ['.pdf', '.txt', '.md'];
    const lower = f.name.toLowerCase();
    if (!allowed.some(function (ext) { return lower.endsWith(ext); })) {
      toast('Only PDF, TXT, or Markdown files are accepted', 'err');
      input.value = '';
      return;
    }
    const MAX = 12 * 1024 * 1024;
    if (f.size > MAX) {
      toast('File is too large (max 12 MB)', 'err');
      input.value = '';
      return;
    }

    const st = $('#upload-status');
    if (st) {
      clearChildren(st);
      st.appendChild(el('div', { style: 'font-size:.85rem;color:var(--muted);margin-top:1rem' }, ['Adding to your memory…']));
    }

    const fd = new FormData();
    fd.append('file', f);
    fd.append('doc_type', ($('#doc-type') || {}).value || 'general');
    try {
      const res = await fetch(API + '/api/memory/upload', { method: 'POST', body: fd });
      const data = await res.json().catch(function () { return {}; });
      if (!res.ok || !data.success) {
        if (st) {
          clearChildren(st);
          st.appendChild(el('div', { style: 'font-size:.85rem;color:#f87171;margin-top:1rem' }, [data.error || 'Upload failed']));
        }
        return;
      }
      if (st) {
        clearChildren(st);
        st.appendChild(el('div', { style: 'font-size:.85rem;color:#4ade80;margin-top:1rem' }, ['Added to memory']));
      }
      loadDocs();
    } catch (e) {
      if (st) {
        clearChildren(st);
        st.appendChild(el('div', { style: 'font-size:.85rem;color:#f87171;margin-top:1rem' }, ['Upload failed']));
      }
    } finally {
      input.value = '';
    }
  }

  async function loadDocs() {
    const list = $('#doc-list');
    if (!list) return;
    try {
      const res = await fetch(API + '/api/memory/documents');
      const data = await res.json().catch(function () { return { documents: [] }; });
      clearChildren(list);
      (data.documents || []).forEach(function (d) {
        list.appendChild(el('div', { class: 'doc-item' }, [
          el('div', {}, [
            el('div', { class: 'doc-name' }, [d.name || 'Untitled']),
            el('div', { class: 'doc-meta' }, [(d.chunks || 0) + ' chunks indexed']),
          ]),
        ]));
      });
    } catch (e) { /* ignore */ }
  }

  async function queryMem() {
    const q = (($('#mem-q') || {}).value || '').trim();
    if (!q) { toast('Enter a question to search', 'err'); return; }
    const elOut = $('#mem-out');
    if (elOut) {
      clearChildren(elOut);
      elOut.appendChild(el('div', { class: 'spinner', style: 'margin-top:2rem' }));
    }
    try {
      const res = await fetch(API + '/api/memory/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      });
      const data = await res.json().catch(function () { return {}; });
      if (!elOut) return;
      clearChildren(elOut);
      const wrap = el('div', { class: 'memory-answer' }, [
        el('div', { class: 'section-label' }, ['Answer']),
        el('div', { class: 'answer-text' }, [data.answer || 'No answer was returned.']),
      ]);
      const sources = (data.sources || []).map(function (s) {
        return el('span', { class: 'source-chip' }, ['Source: ' + s]);
      });
      if (sources.length) {
        const srcWrap = el('div', { style: 'margin-top:1.25rem' }, sources);
        wrap.appendChild(srcWrap);
      }
      elOut.appendChild(wrap);
    } catch (e) {
      if (elOut) {
        clearChildren(elOut);
        elOut.appendChild(el('div', { class: 'memory-answer' }, [
          el('div', { class: 'answer-text' }, ['Search failed. Please try again.']),
        ]));
      }
    }
  }

  // ─── Brief engine ───────────────────────────────────────────────────────
  function buildMetrics() {
    const grid = $('#metrics-grid');
    if (!grid) return;
    clearChildren(grid);
    METRICS.forEach(function (m, i) {
      const lbl = el('input', { class: 'metric-lbl-input', id: 'm-l' + i, type: 'text', value: m.l, 'aria-label': 'Metric label ' + (i + 1) });
      const val = el('input', { class: 'metric-val-input', id: 'm-v' + i, type: 'text', placeholder: m.p, 'aria-label': 'Metric value ' + (i + 1) });
      grid.appendChild(el('div', { class: 'metric-box' }, [lbl, val]));
    });
  }

  async function genDeck() {
    const company = (($('#co-name') || {}).value || '').trim();
    const period = (($('#co-period') || {}).value || '').trim();
    if (!company || !period) { toast('Add a company name and period', 'err'); return; }

    const payload = {
      company_name: company,
      period: period,
      highlights: (($('#b-wins') || {}).value || '').trim(),
      challenges: (($('#b-risks') || {}).value || '').trim(),
      ask: (($('#b-ask') || {}).value || '').trim(),
      metrics: {},
    };
    METRICS.forEach(function (_, i) {
      const labelEl = document.getElementById('m-l' + i);
      const valEl = document.getElementById('m-v' + i);
      if (labelEl && valEl && labelEl.value) {
        payload.metrics[labelEl.value] = valEl.value;
      }
    });

    const btn = $('#brief-btn');
    if (btn) btn.disabled = true;
    const L = $('#brief-loading');
    if (L) L.classList.add('active');
    const out = $('#brief-out');
    if (out) clearChildren(out);

    try {
      const res = await fetch(API + '/api/brief/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(function () { return {}; });
      if (!res.ok || !data.success) {
        toast(data.error || 'Could not generate the deck', 'err');
        return;
      }
      if (out) {
        const link = el('a', {
          href: data.download_url || '#',
          class: 'btn-primary',
          download: '',
          rel: 'noopener',
        }, ['Download PowerPoint']);
        out.appendChild(el('div', { class: 'deck-done reveal active' }, [
          el('div', { class: 'deck-done-title' }, ['Your deck is ready']),
          el('div', { style: 'color:var(--muted);margin-bottom:1.75rem' }, [(data.slides || 0) + ' slides generated']),
          link,
        ]));
      }
    } catch (e) {
      toast('Network issue. Please try again.', 'err');
    } finally {
      if (btn) btn.disabled = false;
      if (L) L.classList.remove('active');
    }
  }

  // ─── Hero phrase cycle ──────────────────────────────────────────────────
  function startPhraseCycle() {
    const node = $('#type-text');
    if (!node) return;
    let pIdx = 0;
    setInterval(function () {
      node.classList.add('swap-out');
      setTimeout(function () {
        pIdx = (pIdx + 1) % PHRASES.length;
        node.textContent = PHRASES[pIdx];
        node.classList.remove('swap-out');
      }, 380);
    }, 3200);
  }

  // ─── Action dispatch ────────────────────────────────────────────────────
  const ACTIONS = {
    'show-page': function (el) { showPage(el.dataset.page); },
    'open-debate': function () { showPage('debate'); },
    'open-pricing': function () { showPage('pricing'); },
    'open-waitlist': function () { showPage('waitlist'); },
    'open-memory': function () { showPage('memory'); },
    'open-brief': function () { showPage('brief'); },
    'open-home': function () { showPage('home'); },
    'open-how': function () { showPage('how'); },
    'open-about': function () { showPage('about'); },
    'open-sentinel': function () { window.location.assign('/sentinel'); },
    'open-terms': function () { showPage('terms'); },
    'open-privacy': function () { showPage('privacy'); },
    'toggle-nav': function () { toggleMobileNav(); },
    'toggle-theme': function () { toggleTheme(); },
    'open-file': function () { const f = $('#file-in'); if (f) f.click(); },
    'start-signup': function () { startSignup(); },
    'run-debate': function () { runDebate(); },
    'query-mem': function () { queryMem(); },
    'gen-deck': function () { genDeck(); },
  };

  function bindActions(root) {
    $$('[data-action]', root).forEach(function (el) {
      el.addEventListener('click', function (ev) {
        const action = el.dataset.action;
        const fn = ACTIONS[action];
        if (fn) {
          ev.preventDefault();
          fn(el, ev);
        }
      });
    });
  }

  // ─── Boot ───────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    applyTheme(getPreferredTheme());
    bindActions(document);

    const fileIn = $('#file-in');
    if (fileIn) fileIn.addEventListener('change', function () { uploadDoc(fileIn); });

    document.addEventListener('click', function (ev) {
      const nav = $('nav');
      if (nav && nav.classList.contains('open') && !nav.contains(ev.target)) {
        closeMobileNav();
      }
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') closeMobileNav();
    });

    const observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) entry.target.classList.add('active');
      });
    }, { threshold: 0.1 });
    $$('.reveal').forEach(function (el) { observer.observe(el); });

    buildMetrics();
    startPhraseCycle();

    const hashPage = (window.location.hash || '').replace('#', '').trim();
    const pathPage = (window.location.pathname || '').replace(/^\/+/, '').trim();
    if (pathPage === 'how' && document.getElementById('page-how')) {
      showPage('how');
    } else if (pathPage === 'pricing' && document.getElementById('page-pricing')) {
      showPage('pricing');
    } else if (pathPage === 'about' && document.getElementById('page-about')) {
      showPage('about');
    } else if ((pathPage === 'terms' || pathPage === 'tos') && document.getElementById('page-terms')) {
      showPage('terms');
    } else if (pathPage === 'privacy' && document.getElementById('page-privacy')) {
      showPage('privacy');
    } else if (pathPage === 'waitlist' && document.getElementById('page-waitlist')) {
      showPage('waitlist');
    } else if (hashPage && document.getElementById('page-' + hashPage)) {
      showPage(hashPage);
    }
    // Always strip any existing hash from the address bar so nothing like "#home" sticks around.
    if (window.location.hash && history && history.replaceState) {
      try {
        history.replaceState(null, '', window.location.pathname + window.location.search);
      } catch (_e) { /* noop */ }
    }

    const params = new URLSearchParams(window.location.search);
    if (params.get('trial') === '1') {
      showPage('debate');
      toast('Trial access enabled. Welcome to Fourseat.', 'ok');
    }

    if ('serviceWorker' in navigator && window.isSecureContext) {
      navigator.serviceWorker.register('/frontend/sw.js').catch(function () { /* noop */ });
    }
  });
})();
