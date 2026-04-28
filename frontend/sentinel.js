/* Fourseat Sentinel - walkthrough controller
 * Pure client-side animation, no API calls.
 * Lives as an external file because our strict CSP disallows inline <script>.
 */
(function () {
  'use strict';
  const THEME_KEY = 'fourseat-theme';

  // ── Scenarios: 10 hand-written decision briefings, each with 5 inbound items
  // and a Chair verdict. Priorities (P0–P3) are assigned from "data-pri" on
  // each row during stage 2 of the walkthrough.
  const scenarios = [
    {
      title: 'Acme Capital term sheet',
      sub: 'Series A · sign-off by Friday 5pm ET',
      rows: [
        { pri: 'P0', subject: 'Term sheet v3 · sign-off by Friday', meta: 'sarah.lin@acme-capital.com · 2h ago' },
        { pri: 'P0', subject: 'Cease and desist · trademark claim', meta: 'legal@outbound-firm.com · 4h ago' },
        { pri: 'P1', subject: 'Pilot · 50 seats for portfolio founders', meta: 'andre@prospect-enterprise.com · 6h ago' },
        { pri: 'P2', subject: 'TechCrunch interview request', meta: 'jenna@techcrunch.com · 1d ago' },
        { pri: 'P3', subject: '50% off web hosting this weekend', meta: 'deals@newsletter.com · 1d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · Term sheet v3',
      verdictConf: 'High confidence',
      verdictBody:
        'Counter to $20M pre, keep 1x non-participating. Decline the ratchet. Reply before IC closes Friday 5pm ET.',
    },
    {
      title: 'Lead engineer resignation risk',
      sub: 'Retention · Maya Patel (Staff, Platform)',
      rows: [
        { pri: 'P0', subject: '"Can we talk 1:1 this afternoon?"', meta: 'maya.patel@fourseat.dev · 25m ago' },
        { pri: 'P1', subject: 'Recruiter · Staff role at Stripe, $420k OTE', meta: 'kim@sterling-talent.com · 3h ago' },
        { pri: 'P1', subject: 'On-call rotation feedback · sprint review', meta: 'ops@fourseat.dev · 5h ago' },
        { pri: 'P2', subject: 'All-hands deck draft · v2', meta: 'hr@fourseat.dev · 1d ago' },
        { pri: 'P3', subject: 'Office snack preferences survey', meta: 'operations@fourseat.dev · 2d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · Retention risk',
      verdictConf: 'High confidence',
      verdictBody:
        'Hold the 1:1 today, not Friday. Lead with scope, not comp. Line up a retention grant option before you walk in.',
    },
    {
      title: 'Q2 board meeting prep',
      sub: 'Tuesday 9am PT · 5 directors',
      rows: [
        { pri: 'P0', subject: 'Board deck · final review requested', meta: 'chair@fourseat-board.com · 1h ago' },
        { pri: 'P1', subject: 'Independent director · pre-read questions', meta: 'helena.ro@partner-group.com · 4h ago' },
        { pri: 'P1', subject: 'CFO · churn cohort numbers don\'t match', meta: 'david@fourseat.dev · 6h ago' },
        { pri: 'P2', subject: 'Legal · updated equity plan for board', meta: 'counsel@outside-firm.com · 12h ago' },
        { pri: 'P3', subject: 'Catering for Tuesday · vegan options?', meta: 'admin@fourseat.dev · 1d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · Board deck',
      verdictConf: 'Medium confidence',
      verdictBody:
        'Lead with the churn cohort mismatch, not the ARR number. Board will ask anyway — surface it on slide 4 with the fix plan.',
    },
    {
      title: 'Inbound acquisition interest',
      sub: 'Strategic buyer · M&A · NDA pending',
      rows: [
        { pri: 'P0', subject: 'Exploratory · acquisition conversation', meta: 'corp.dev@strategic-buyer.com · 45m ago' },
        { pri: 'P1', subject: 'Lead investor · "heard chatter, call me"', meta: 'partner@lead-vc.com · 2h ago' },
        { pri: 'P1', subject: 'Banker intro · Goldman TMT team', meta: 'michael.wong@gs.com · 5h ago' },
        { pri: 'P2', subject: 'Press leak risk · reporter reaching out', meta: 'reporter@wsj.com · 8h ago' },
        { pri: 'P3', subject: 'Office party photos from last Friday', meta: 'team@fourseat.dev · 1d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · M&A inquiry',
      verdictConf: 'High confidence',
      verdictBody:
        'Don\'t engage bilaterally. Sign NDA, tell your lead investor today, and loop in a banker before any number is discussed.',
    },
    {
      title: 'AWS bill surprise',
      sub: 'Infra cost · 3.2x last month',
      rows: [
        { pri: 'P0', subject: 'AWS bill · $148,204 this month (was $46k)', meta: 'billing@amazon.com · 1h ago' },
        { pri: 'P0', subject: 'PagerDuty · prod DB CPU 97% sustained', meta: 'alerts@pagerduty.com · 3h ago' },
        { pri: 'P1', subject: 'Eng · rollout plan for vector index rebuild', meta: 'platform@fourseat.dev · 6h ago' },
        { pri: 'P2', subject: 'Vendor · Pinecone discount if annual', meta: 'sales@pinecone.io · 10h ago' },
        { pri: 'P3', subject: 'Company offsite hotel block reminder', meta: 'travel@fourseat.dev · 2d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · AWS overrun',
      verdictConf: 'High confidence',
      verdictBody:
        'Pause the background embedding job, cap concurrency at 4, move cold vectors to S3. Savings plan review Thursday.',
    },
    {
      title: 'Customer data incident',
      sub: 'Security · 1 enterprise tenant affected',
      rows: [
        { pri: 'P0', subject: 'URGENT · logs show cross-tenant read', meta: 'security@fourseat.dev · 18m ago' },
        { pri: 'P0', subject: 'Enterprise customer · "are we impacted?"', meta: 'ciso@fortune500-customer.com · 32m ago' },
        { pri: 'P1', subject: 'Legal · 72-hour breach notice deadline', meta: 'counsel@outside-firm.com · 2h ago' },
        { pri: 'P2', subject: 'Support · customer asking for SOC 2 report', meta: 'support@fourseat.dev · 5h ago' },
        { pri: 'P3', subject: 'LinkedIn post · someone liked your article', meta: 'notifications@linkedin.com · 1d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · Security incident',
      verdictConf: 'High confidence',
      verdictBody:
        'Rotate keys, freeze the feature flag, call the affected CISO personally within the hour. Start the GDPR 72-hour clock now.',
    },
    {
      title: 'Launch slip decision',
      sub: 'Product · GA date vs. quality',
      rows: [
        { pri: 'P0', subject: 'QA · 3 P0 bugs still open, launch is Wed', meta: 'qa@fourseat.dev · 1h ago' },
        { pri: 'P1', subject: 'Marketing · press embargo lifts 9am Wed', meta: 'comms@fourseat.dev · 4h ago' },
        { pri: 'P1', subject: 'Design partner · blocking on new API', meta: 'cto@design-partner.com · 6h ago' },
        { pri: 'P2', subject: 'Sales · 4 deals waiting on launch', meta: 'sales@fourseat.dev · 12h ago' },
        { pri: 'P3', subject: 'Your flight to SF has been upgraded', meta: 'united@united.com · 1d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · Launch slip',
      verdictConf: 'Medium confidence',
      verdictBody:
        'Ship to design partners Wed, public GA Fri after P0 fixes. Tell comms today — embargo-extend is a 30-minute email, not a crisis.',
    },
    {
      title: 'Co-founder conflict',
      sub: 'CEO · CTO · product vs. platform split',
      rows: [
        { pri: 'P0', subject: 'We need to align. Today. — J', meta: 'julian@fourseat.dev · 12m ago' },
        { pri: 'P1', subject: 'HR · team sensing tension, morale dip', meta: 'people@fourseat.dev · 4h ago' },
        { pri: 'P1', subject: 'Board · "anything we should know?"', meta: 'chair@fourseat-board.com · 6h ago' },
        { pri: 'P2', subject: 'Exec coach · Tuesday session confirmed', meta: 'booking@exec-coach.com · 1d ago' },
        { pri: 'P3', subject: 'Weekly newsletter · founder burnout edition', meta: 'hello@founder-digest.com · 2d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · Co-founder sync',
      verdictConf: 'Medium confidence',
      verdictBody:
        'Meet today. No deck, no notes. Align on one sentence: who owns what for the next 90 days. Then tell the team, not the board.',
    },
    {
      title: 'Layoff decision',
      sub: 'People · 18 months of runway at stake',
      rows: [
        { pri: 'P0', subject: 'CFO · burn model, 3 scenarios attached', meta: 'david@fourseat.dev · 30m ago' },
        { pri: 'P1', subject: 'Legal · WARN Act thresholds memo', meta: 'counsel@outside-firm.com · 3h ago' },
        { pri: 'P1', subject: 'Head of People · severance policy draft', meta: 'people@fourseat.dev · 5h ago' },
        { pri: 'P2', subject: 'Board · requested all-hands talking points', meta: 'chair@fourseat-board.com · 10h ago' },
        { pri: 'P3', subject: 'Re: coffee next week?', meta: 'old-friend@gmail.com · 2d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · Workforce reduction',
      verdictConf: 'Medium confidence',
      verdictBody:
        'Scenario B: 14% reduction, 2 months severance, 6 months extended healthcare. Announce in one all-hands, same day, no rumors.',
    },
    {
      title: 'Strategic vs. financial round',
      sub: 'Fundraise · $25M Series B',
      rows: [
        { pri: 'P0', subject: 'Strategic · Oracle wants to lead, 30-day exclusive', meta: 'corpdev@oracle.com · 1h ago' },
        { pri: 'P0', subject: 'Lead fund · "don\'t sign exclusivity"', meta: 'partner@lead-vc.com · 2h ago' },
        { pri: 'P1', subject: 'Ex-CEO mentor · strategic $ comes with strings', meta: 'rachel@former-unicorn.com · 5h ago' },
        { pri: 'P2', subject: 'PR · strategic lead = acquisition signal?', meta: 'pr@fourseat.dev · 11h ago' },
        { pri: 'P3', subject: 'Amazon · your package was delivered', meta: 'auto-confirm@amazon.com · 1d ago' },
      ],
      verdictHead: 'Chair verdict · P0 · Lead investor choice',
      verdictConf: 'High confidence',
      verdictBody:
        'Take the financial lead. Bring Oracle in as a strategic LP at <20%, no board seat, no ROFR. Don\'t sign exclusivity with either.',
    },
  ];

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const stageLabel = document.getElementById('sx-stage-label');
  const msgList = document.getElementById('sx-msg-list');
  const verdict = document.getElementById('sx-verdict');
  const verdictHead = document.getElementById('sx-verdict-head');
  const verdictConf = document.getElementById('sx-verdict-conf');
  const verdictBody = document.getElementById('sx-verdict-body');
  const scenarioTitle = document.getElementById('sx-scenario-title');
  const scenarioSub = document.getElementById('sx-scenario-sub');
  const scenarioCounter = document.getElementById('sx-scenario-counter');
  const replay = document.getElementById('sx-replay');
  const nextBtn = document.getElementById('sx-next');
  const dateEl = document.getElementById('sx-date');
  const demo = document.querySelector('.sx-demo');
  const themeToggle = document.getElementById('sentinel-theme-toggle');
  const connectorEls = {
    gmail: document.getElementById('sx-gmail'),
    slack: document.getElementById('sx-slack'),
    teams: document.getElementById('sx-teams'),
  };

  function getPreferredTheme() {
    const saved = window.localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
    return (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
  }

  function applyTheme(theme) {
    const nextTheme = (theme === 'light') ? 'light' : 'dark';
    document.body.setAttribute('data-theme', nextTheme);
    document.documentElement.style.colorScheme = nextTheme;

    const metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) metaTheme.setAttribute('content', nextTheme === 'light' ? '#f6f2ea' : '#110f0d');

    if (themeToggle) {
      const label = themeToggle.querySelector('.theme-toggle-label');
      const goingTo = nextTheme === 'dark' ? 'light' : 'dark';
      themeToggle.setAttribute('aria-label', 'Switch to ' + goingTo + ' mode');
      themeToggle.setAttribute('aria-pressed', nextTheme === 'dark' ? 'true' : 'false');
      themeToggle.setAttribute('data-theme', nextTheme);
      if (label) label.textContent = nextTheme === 'dark' ? 'Dark' : 'Light';
    }
  }

  function toggleTheme() {
    const current = document.body.getAttribute('data-theme') || getPreferredTheme();
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    window.localStorage.setItem(THEME_KEY, next);
  }

  async function loadConnectorStatus() {
    try {
      const resp = await fetch('/api/sentinel/connectors');
      const data = await resp.json();
      const connectors = (data && data.connectors) || {};
      ['gmail', 'slack', 'teams'].forEach(function (key) {
        const el = connectorEls[key];
        if (!el) return;
        const ok = Boolean(connectors[key] && connectors[key].configured);
        el.classList.remove('ok', 'off', 'pending');
        if (ok) {
          el.classList.add('ok');
          el.textContent = key.charAt(0).toUpperCase() + key.slice(1) + ' · connected';
        } else {
          el.classList.add('pending');
          el.textContent = key.charAt(0).toUpperCase() + key.slice(1) + ' · coming soon';
        }
      });
    } catch (_e) {
      ['gmail', 'slack', 'teams'].forEach(function (key) {
        const el = connectorEls[key];
        if (!el) return;
        el.classList.remove('ok', 'off');
        el.classList.add('pending');
        el.textContent = key.charAt(0).toUpperCase() + key.slice(1) + ' · coming soon';
      });
    }
  }

  if (dateEl) {
    const d = new Date();
    dateEl.textContent = d.toISOString().slice(0, 10);
  }

  const reduced =
    window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let index = 0;
  let playing = false;
  let cancelToken = 0;

  function clearChildren(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'class') node.className = attrs[k];
        else if (k === 'dataset') {
          Object.keys(attrs[k]).forEach(function (dk) { node.dataset[dk] = attrs[k][dk]; });
        } else node.setAttribute(k, attrs[k]);
      });
    }
    if (text != null) node.appendChild(document.createTextNode(text));
    return node;
  }

  function renderScenario(sc) {
    if (scenarioTitle) scenarioTitle.textContent = sc.title;
    if (scenarioSub) scenarioSub.textContent = sc.sub;
    if (scenarioCounter) scenarioCounter.textContent = (index + 1) + ' / ' + scenarios.length;

    if (msgList) {
      clearChildren(msgList);
      sc.rows.forEach(function (row) {
        const li = el('li', { class: 'sx-msg', dataset: { pri: row.pri } });
        li.appendChild(el('span', { class: 'sx-pri' }, '—'));
        const body = el('div');
        body.appendChild(el('div', { class: 'sx-msg-subject' }, row.subject));
        body.appendChild(el('div', { class: 'sx-msg-meta' }, row.meta));
        li.appendChild(body);
        msgList.appendChild(li);
      });
    }

    if (verdictHead) verdictHead.textContent = sc.verdictHead;
    if (verdictConf) verdictConf.textContent = sc.verdictConf;
    if (verdictBody) verdictBody.textContent = sc.verdictBody;
    if (verdict) verdict.classList.remove('in');
  }

  function setLabel(num, text) {
    if (!stageLabel) return;
    clearChildren(stageLabel);
    const n = el('span', { class: 'num' }, String(num));
    const t = el('span', null, text);
    stageLabel.appendChild(n);
    stageLabel.appendChild(t);
  }

  function wait(ms, token) {
    return new Promise(function (resolve) {
      const delay = reduced ? 0 : ms;
      const id = setTimeout(function () {
        if (token !== cancelToken) return;
        resolve();
      }, delay);
      void id;
    });
  }

  async function play() {
    if (playing) return;
    playing = true;
    cancelToken += 1;
    const token = cancelToken;

    const sc = scenarios[index];
    renderScenario(sc);

    setLabel('1', 'Scanning inbound');
    const messages = Array.prototype.slice.call(document.querySelectorAll('#sx-msg-list .sx-msg'));
    for (const m of messages) {
      if (token !== cancelToken) { playing = false; return; }
      m.classList.add('in', 'scanning');
      await wait(240, token);
    }
    await wait(420, token);
    if (token !== cancelToken) { playing = false; return; }
    messages.forEach(function (m) { m.classList.remove('scanning'); });

    setLabel('2', 'Prioritising by urgency');
    for (const m of messages) {
      if (token !== cancelToken) { playing = false; return; }
      const pri = m.dataset.pri;
      const pill = m.querySelector('.sx-pri');
      if (pill && pri) {
        pill.classList.add(pri.toLowerCase());
        pill.textContent = pri;
      }
      m.classList.add('tagged');
      await wait(230, token);
    }
    await wait(520, token);
    if (token !== cancelToken) { playing = false; return; }

    setLabel('3', 'Board debate & chair verdict');
    if (verdict) verdict.classList.add('in');
    await wait(4600, token);
    if (token !== cancelToken) { playing = false; return; }

    playing = false;

    index = (index + 1) % scenarios.length;
    if (!reduced) {
      await wait(900, token);
      if (token !== cancelToken) return;
      play();
    }
  }

  function goNext() {
    cancelToken += 1;
    playing = false;
    index = (index + 1) % scenarios.length;
    play();
  }

  function goReplay() {
    cancelToken += 1;
    playing = false;
    play();
  }

  if (replay) replay.addEventListener('click', goReplay);
  if (nextBtn) nextBtn.addEventListener('click', goNext);
  if (themeToggle) themeToggle.addEventListener('click', toggleTheme);
  applyTheme(getPreferredTheme());
  loadConnectorStatus();

  if (!demo) return;

  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver(
      function (entries, obs) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            play();
            obs.disconnect();
          }
        });
      },
      { threshold: 0.25 }
    );
    io.observe(demo);
  } else {
    play();
  }
})();
