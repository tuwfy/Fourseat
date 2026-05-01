// Fourseat Help Center SPA
(function(){
  const PAGES = {
    // ── HELP CENTER ──
    "getting-started": {
      tab:"help-center", breadcrumb:"Help Center", title:"Getting Started",
      content:`<p>Welcome to Fourseat. This guide walks you through connecting your first source and receiving your first verdict.</p>
        <h3>1) Create your workspace</h3><p>Sign up at <a href="/">fourseat.dev</a> and create a new workspace. Each workspace is an isolated environment for one company.</p>
        <h3>2) Connect your first source</h3><p>Navigate to Oracle and click <strong>Connect</strong> next to any supported source: Stripe, QuickBooks, GitHub, Linear, or Slack. Each uses one-click OAuth — no API keys to manage.</p>
        <h3>3) Wait for backfill</h3><p>Oracle backfills 90 days of history from each connected source. This typically takes 2-5 minutes depending on data volume.</p>
        <h3>4) Review your first verdict</h3><p>Once the backfill completes, Oracle runs its cross-source detection rules automatically. Any anomalies will appear as verdicts in your dashboard.</p>`,
      toc:["Create your workspace","Connect your first source","Wait for backfill","Review your first verdict"]
    },
    "connectors": {
      tab:"help-center", breadcrumb:"Help Center", title:"Connecting Sources",
      content:`<p>Oracle supports five data sources. Each connector uses OAuth 2.0 for secure, one-click authorization.</p>
        <h3>Stripe</h3><p>Connects to your Stripe account to monitor charges, subscriptions, invoices, and failed payments. Oracle watches for churn clusters, NRR drops, concentration risk, and failed payment leakage.</p>
        <h3>QuickBooks</h3><p>Syncs your P&L statements, expense reports, and accounts receivable data. Oracle flags expense anomalies, AR aging risks, and budget deviations.</p>
        <h3>GitHub</h3><p>Monitors repository activity including deploy frequency, PR cycle time, review bottlenecks, and commit velocity. Oracle correlates engineering output with revenue signals.</p>
        <h3>Linear</h3><p>Tracks sprint velocity, scope creep, backlog health, and bug counts. Oracle cross-references sprint performance with churn data to detect misalignment.</p>
        <h3>Slack</h3><p>Analyzes channel sentiment, escalation patterns, and team health signals. Oracle detects burnout indicators, frustration spikes, and communication breakdowns. <strong>Note:</strong> Fourseat never reads private DMs — only public channels you explicitly authorize.</p>`,
      toc:["Stripe","QuickBooks","GitHub","Linear","Slack"]
    },
    "verdicts": {
      tab:"help-center", breadcrumb:"Help Center", title:"Understanding Verdicts",
      content:`<p>A verdict is a single, actionable decision produced by Oracle's four-advisor board when a cross-source anomaly is detected.</p>
        <h3>Anatomy of a verdict</h3><p>Each verdict includes: a <strong>one-liner</strong> summary, four advisor perspectives (Strategy, Finance, Tech, Contrarian), a <strong>priority level</strong> (P0/P1/P2), a <strong>confidence score</strong>, recommended actions, and watch metrics.</p>
        <h3>Priority levels</h3><p><strong>P0:</strong> Requires immediate attention. Revenue impact is happening now.<br/><strong>P1:</strong> Important but not urgent. Should be addressed this week.<br/><strong>P2:</strong> Informational. Worth monitoring but no action needed yet.</p>
        <h3>Cross-source verdicts</h3><p>The most powerful verdicts correlate signals across multiple sources. For example: "GitHub deploy frequency dropped 67% while Stripe churn spiked 4x in the same window." These cross-source correlations are blind spots that no single-source tool can detect.</p>
        <h3>Resolving verdicts</h3><p>Click <strong>Mark Resolved</strong> to close a verdict. Every resolution feeds back into Oracle's learning loop, improving future detection accuracy.</p>`,
      toc:["Anatomy of a verdict","Priority levels","Cross-source verdicts","Resolving verdicts"]
    },
    "board-decks": {
      tab:"help-center", breadcrumb:"Help Center", title:"Board Decks",
      content:`<p>Oracle can generate a board-ready PowerPoint (.pptx) from any verdict with one click.</p>
        <h3>What's included</h3><p>Each deck contains: an executive summary slide, the four-advisor analysis, supporting evidence and charts, recommended actions, and watch metrics for follow-up.</p>
        <h3>Customization</h3><p>Upload your company logo and brand colors in workspace settings. Decks will automatically use your branding.</p>
        <h3>Sharing</h3><p>Download the .pptx file directly or share a read-only link with your board members. Links expire after 30 days by default.</p>`,
      toc:["What's included","Customization","Sharing"]
    },
    "billing": {
      tab:"help-center", breadcrumb:"Help Center", title:"Billing & Plans",
      content:`<p>Fourseat offers three tiers designed for companies at different stages.</p>
        <h3>Starter (Free)</h3><p>One connected source, up to 3 active verdicts, community support. Perfect for trying Oracle before committing.</p>
        <h3>Pro ($149/mo)</h3><p>All five sources connected, unlimited verdicts, board deck generation, priority support, and 90-day data retention.</p>
        <h3>Enterprise (Custom)</h3><p>Everything in Pro plus SSO/SAML, custom integrations, dedicated success manager, SLA guarantees, and unlimited data retention. <a href="mailto:hello@fourseat.dev">Contact sales</a> for pricing.</p>`,
      toc:["Starter (Free)","Pro ($149/mo)","Enterprise (Custom)"]
    },
    // ── API ──
    "api-overview": {
      tab:"api", breadcrumb:"Fourseat API", title:"API Overview",
      content:`<p>The Fourseat API lets you programmatically access verdicts, snapshots, and connector status. All endpoints return JSON and require Bearer token authentication.</p>
        <h3>Base URL</h3><p><code>https://api.fourseat.dev/v1</code></p>
        <h3>Authentication</h3><p>Include your API key in the Authorization header:<br/><code>Authorization: Bearer fs_live_xxxxxxxxxxxxx</code></p>
        <h3>Rate limits</h3><p>Standard tier: 1,000 requests/minute. Enterprise tier: 10,000 requests/minute. Exceeding limits returns HTTP 429.</p>
        <h3>Versioning</h3><p>The API is versioned via URL path. The current version is <code>v1</code>. We will announce deprecations at least 90 days before removing any endpoint.</p>`,
      toc:["Base URL","Authentication","Rate limits","Versioning"]
    },
    "api-verdicts": {
      tab:"api", breadcrumb:"Fourseat API", title:"Verdicts Endpoint",
      content:`<h3>List verdicts</h3><p><code>GET /v1/verdicts</code></p><p>Returns all open verdicts for the authenticated workspace. Supports <code>?status=open|resolved</code> and <code>?priority=P0|P1|P2</code> query filters.</p>
        <h3>Get verdict</h3><p><code>GET /v1/verdicts/:id</code></p><p>Returns full verdict detail including all four advisor perspectives, evidence, actions, and watch metrics.</p>
        <h3>Resolve verdict</h3><p><code>POST /v1/verdicts/:id/resolve</code></p><p>Marks a verdict as resolved. Accepts an optional <code>resolution_note</code> in the request body.</p>
        <h3>Response format</h3><p>All verdict responses include: <code>id</code>, <code>rule</code>, <code>priority</code>, <code>confidence</code>, <code>one_liner</code>, <code>strategy_view</code>, <code>finance_view</code>, <code>tech_view</code>, <code>contrarian_view</code>, <code>evidence</code>, <code>actions</code>, <code>watch_metrics</code>, <code>created_at</code>, <code>resolved</code>.</p>`,
      toc:["List verdicts","Get verdict","Resolve verdict","Response format"]
    },
    "api-snapshots": {
      tab:"api", breadcrumb:"Fourseat API", title:"Snapshots Endpoint",
      content:`<h3>Get latest snapshot</h3><p><code>GET /v1/snapshots/latest</code></p><p>Returns the most recent company snapshot with MRR, NRR, active subscriptions, and failed payment data.</p>
        <h3>List snapshots</h3><p><code>GET /v1/snapshots?from=2026-01-01&to=2026-04-30</code></p><p>Returns historical snapshots within the specified date range. Maximum range: 90 days.</p>
        <h3>Response format</h3><p>Each snapshot includes: <code>snapshot_date</code>, <code>mrr_cents</code>, <code>nrr_pct</code>, <code>active_subs</code>, <code>top_customer_share</code>, <code>failed_payments_cents</code>, <code>failed_payments_count</code>.</p>`,
      toc:["Get latest snapshot","List snapshots","Response format"]
    },
    "api-connectors": {
      tab:"api", breadcrumb:"Fourseat API", title:"Connectors Endpoint",
      content:`<h3>List connectors</h3><p><code>GET /v1/connectors</code></p><p>Returns the status of all five supported connectors: Stripe, QuickBooks, GitHub, Linear, and Slack.</p>
        <h3>Response format</h3><p>Each connector object includes: <code>name</code>, <code>configured</code> (boolean), <code>last_sync</code> (ISO timestamp), <code>events_ingested</code> (integer), <code>status</code> ("healthy" | "degraded" | "disconnected").</p>
        <h3>Trigger sync</h3><p><code>POST /v1/connectors/:name/sync</code></p><p>Forces an immediate sync for the specified connector. Returns the sync job ID for polling status.</p>`,
      toc:["List connectors","Response format","Trigger sync"]
    },
    "api-webhooks": {
      tab:"api", breadcrumb:"Fourseat API", title:"Webhooks",
      content:`<h3>Overview</h3><p>Fourseat can send webhook notifications to your server when new verdicts are created or when connector status changes.</p>
        <h3>Configure webhooks</h3><p><code>POST /v1/webhooks</code> with <code>{"url": "https://your-server.com/hook", "events": ["verdict.created", "connector.status_changed"]}</code></p>
        <h3>Webhook payload</h3><p>Each webhook includes an <code>event</code> type, a <code>timestamp</code>, and a <code>data</code> object containing the full verdict or connector status.</p>
        <h3>Verification</h3><p>All webhooks are signed with HMAC-SHA256. Verify the <code>X-Fourseat-Signature</code> header against your webhook secret to ensure authenticity.</p>`,
      toc:["Overview","Configure webhooks","Webhook payload","Verification"]
    },
    // ── POLICIES (existing) ──
    "platform-tos": {
      tab:"policies", breadcrumb:"Terms of Service", title:"Platform Terms of Service",
      content:`<p>These Platform Terms of Service govern your access to the Fourseat API and core infrastructure. <strong>By utilizing the Fourseat API or related developer tools, you agree to adhere strictly to these guidelines.</strong></p>
        <h3>1) Usage Limits and Quotas</h3><p>API requests are subject to strict rate limits to ensure stability across all workspaces. Standard tiers allow up to 1,000 requests per minute.</p>
        <h3>2) Data Ingestion Requirements</h3><p>You must not submit PII to non-PII compliance endpoints. All data must be sanitized according to your organization's compliance standards.</p>
        <h3>3) SLA and Uptime</h3><p>Fourseat guarantees 99.9% uptime for Enterprise customers. Scheduled maintenance windows will be communicated 48 hours in advance.</p>
        <h3>4) Termination</h3><p>We reserve the right to suspend API access immediately if we detect malicious activity, reverse engineering, or unauthorized data scraping.</p>`,
      toc:["Usage Limits and Quotas","Data Ingestion Requirements","SLA and Uptime","Termination"]
    },
    "app-tos": {
      tab:"policies", breadcrumb:"Terms of Service", title:"Application Terms of Service",
      content:`<p>These Application Terms apply specifically to the Fourseat Web Dashboard and End-User interfaces.</p>
        <h3>1) Account Security</h3><p>You are responsible for maintaining the security of your credentials. Fourseat recommends enabling MFA for all users with access to financial verdicts.</p>
        <h3>2) Output Ownership</h3><p>You retain full ownership of all board decks, PDF exports, and verdicts generated by your workspace.</p>
        <h3>3) Acceptable Use</h3><p>You agree not to use Fourseat to process illegal transactions, harass individuals, or circumvent regional compliance laws.</p>`,
      toc:["Account Security","Output Ownership","Acceptable Use"]
    },
    "user-tos": {
      tab:"policies", breadcrumb:"Terms of Service", title:"User Terms of Service",
      content:`<p>By registering for a Fourseat account, you agree to these terms. Users must be at least 18 years of age. Fourseat is a decision-support tool and should not replace professional counsel.</p>`,
      toc:[]
    },
    "vdp": {
      tab:"policies", breadcrumb:"Terms of Service", title:"Vulnerability Disclosure Policy",
      content:`<p>Fourseat is committed to ensuring the security of our customers' data.</p>
        <h3>1) Scope</h3><p>Our primary application (fourseat.dev) and API endpoints are in scope. Third-party services are out of scope.</p>
        <h3>2) Safe Harbor</h3><p>If you conduct security research in good faith and comply with this policy, we will not pursue legal action.</p>
        <h3>3) Reporting</h3><p>Submit detailed reports to security@fourseat.dev. We aim to acknowledge within 24 hours.</p>`,
      toc:["Scope","Safe Harbor","Reporting"]
    },
    "privacy": {
      tab:"policies", breadcrumb:"Policies", title:"Privacy Policy",
      content:`<p>At Fourseat, we take your privacy seriously. <strong>By using or accessing our Services, you acknowledge that you accept the practices outlined below.</strong></p>
        <ul><li>We do not allow third parties to use your Personal Data to train AI models.</li><li>We only use De-Identified Data to train AI models, <a href="#">which you can opt-out of</a>.</li><li>We store Personal Data in AWS servers in the U.S., encrypted at rest and in transit.</li></ul>
        <h3>1) Data we collect</h3><p>Account/contact details, waitlist submissions, user inputs, uploaded files, and basic operational logs.</p>
        <h3>2) How we use data</h3><p>To provide core product functions, improve reliability, detect abuse, and communicate account updates.</p>
        <h3>3) Processors and vendors</h3><p>We use Vercel, AWS, OpenAI, and Anthropic to process requests for service delivery.</p>
        <h3>4) Security</h3><p>Encryption in transit, strict access controls, request validation, rate limiting, and hardened security headers.</p>
        <h3>5) Retention and deletion</h3><p>We retain data as needed. Request full deletion by emailing <a href="mailto:hello@fourseat.dev">hello@fourseat.dev</a>.</p>
        <h3>6) Your rights</h3><p>You may have rights to access, correct, export, or delete your data under GDPR, CCPA, or other privacy laws.</p>`,
      toc:["Data we collect","How we use data","Processors and vendors","Security","Retention and deletion","Your rights"]
    },
    "dpa": {
      tab:"policies", breadcrumb:"Policies", title:"Data Processing Addendum",
      content:`<p>This DPA supplements the Terms of Service when Fourseat processes personal data subject to GDPR or CCPA on your behalf.</p>
        <h3>1) Processing Instructions</h3><p>Fourseat will only process personal data according to your documented instructions.</p>
        <h3>2) Subprocessors</h3><p>You authorize Fourseat to engage Subprocessors. We will notify you of any changes.</p>`,
      toc:["Processing Instructions","Subprocessors"]
    },
    "copyright": {
      tab:"policies", breadcrumb:"Policies", title:"Copyright Dispute Policy",
      content:`<p>Fourseat respects intellectual property rights and complies with the DMCA. Send notices to dmca@fourseat.dev.</p>`,
      toc:[]
    },
    "pm-api": {
      tab:"policies", breadcrumb:"Security Reports", title:"Post-Mortem: API Key Exposure",
      content:`<p><strong>Date:</strong> February 14, 2026</p><p><strong>Summary:</strong> A non-production API key was committed to a public repository for 14 minutes.</p>
        <h3>Impact</h3><p>No customer data was exposed. The key was isolated to a staging environment.</p>
        <h3>Resolution</h3><p>Key revoked within 15 minutes. Server-side secret scanning now mandatory on all PRs.</p>`,
      toc:["Impact","Resolution"]
    },
    "pm-workspace": {
      tab:"policies", breadcrumb:"Security Reports", title:"Post-Mortem: Workspace Auto-Join",
      content:`<p><strong>Date:</strong> January 8, 2026</p><p><strong>Summary:</strong> A SAML SSO bug allowed domain-matching users to auto-join workspaces without admin approval.</p>
        <h3>Impact</h3><p>Three enterprise workspaces affected. No sensitive data accessed.</p>
        <h3>Resolution</h3><p>Hotfixed SSO flow and added mandatory Admin Approval Queue.</p>`,
      toc:["Impact","Resolution"]
    },
    "pm-logout": {
      tab:"policies", breadcrumb:"Security Reports", title:"Post-Mortem: Session Logout",
      content:`<p><strong>Date:</strong> November 22, 2025</p><p><strong>Summary:</strong> 'Log out of all devices' failed to invalidate active JWT tokens on edge servers.</p>
        <h3>Resolution</h3><p>Tokens now checked against a centralized Redis blocklist on every request.</p>`,
      toc:["Resolution"]
    }
  };

  // Sidebar nav groups per tab
  const SIDEBAR = {
    "help-center": [
      {title:"Getting Started", items:[
        {id:"getting-started",label:"Getting Started"},
        {id:"connectors",label:"Connecting Sources"},
      ]},
      {title:"Using Oracle", items:[
        {id:"verdicts",label:"Understanding Verdicts"},
        {id:"board-decks",label:"Board Decks"},
      ]},
      {title:"Account", items:[
        {id:"billing",label:"Billing & Plans"},
      ]}
    ],
    "api": [
      {title:"Reference", items:[
        {id:"api-overview",label:"Overview"},
        {id:"api-verdicts",label:"Verdicts"},
        {id:"api-snapshots",label:"Snapshots"},
        {id:"api-connectors",label:"Connectors"},
        {id:"api-webhooks",label:"Webhooks"},
      ]}
    ],
    "policies": [
      {title:"Terms of Service", items:[
        {id:"platform-tos",label:"Platform Terms of Service"},
        {id:"app-tos",label:"Application Terms of Service"},
        {id:"user-tos",label:"User Terms of Service"},
        {id:"vdp",label:"Vulnerability Disclosure Policy"},
      ]},
      {title:"Policies", items:[
        {id:"privacy",label:"Privacy Policy"},
        {id:"dpa",label:"Data Processing Addendum"},
        {id:"copyright",label:"Copyright Dispute Policy"},
      ]},
      {title:"Security Reports", items:[
        {id:"pm-api",label:"Post-Mortem: API Key Exposure"},
        {id:"pm-workspace",label:"Post-Mortem: Workspace Auto-Join"},
        {id:"pm-logout",label:"Post-Mortem: Session Logout"},
      ]}
    ]
  };

  const DEFAULT_PAGE = {
    "help-center":"getting-started",
    "api":"api-overview",
    "policies":"privacy"
  };

  const sidebar = document.querySelector('.sidebar');
  const bcEl = document.getElementById('bc');
  const titleEl = document.getElementById('p-title');
  const contentEl = document.getElementById('p-content');
  const tocList = document.getElementById('toc-list');
  let currentTab = 'policies';

  function buildSidebar(tab) {
    // Keep header and search
    const header = sidebar.querySelector('.sidebar-header');
    const search = sidebar.querySelector('.search-box');
    sidebar.innerHTML = '';
    if(header) sidebar.appendChild(header);
    if(search) sidebar.appendChild(search);

    const groups = SIDEBAR[tab] || [];
    groups.forEach(g => {
      const sec = document.createElement('div');
      sec.className = 'nav-section';
      const t = document.createElement('div');
      t.className = 'nav-title';
      t.textContent = g.title;
      sec.appendChild(t);
      g.items.forEach(item => {
        const a = document.createElement('a');
        a.className = 'nav-link';
        a.dataset.page = item.id;
        a.textContent = item.label;
        a.href = '#';
        a.addEventListener('click', e => { e.preventDefault(); loadPage(item.id); });
        sec.appendChild(a);
      });
      sidebar.appendChild(sec);
    });
  }

  function loadPage(pageId) {
    const data = PAGES[pageId];
    if (!data) return;

    bcEl.textContent = data.breadcrumb;
    titleEl.textContent = data.title;
    contentEl.innerHTML = data.content;

    // TOC
    tocList.innerHTML = '';
    if (data.toc && data.toc.length) {
      data.toc.forEach((h,i) => {
        const a = document.createElement('a');
        a.className = 'toc-link';
        a.href = '#';
        a.textContent = h;
        if(i===0) a.style.color = 'var(--fg)';
        tocList.appendChild(a);
      });
    } else {
      tocList.innerHTML = '<span style="color:var(--muted);font-size:0.85rem;">No sections</span>';
    }

    // Active link
    sidebar.querySelectorAll('.nav-link').forEach(l => {
      l.classList.toggle('active', l.dataset.page === pageId);
    });

    document.querySelector('.main-wrap').scrollTop = 0;
  }

  function switchTab(tab) {
    currentTab = tab;
    // Update top nav
    document.querySelectorAll('.top-link[data-tab]').forEach(l => {
      l.classList.toggle('active', l.dataset.tab === tab);
    });
    buildSidebar(tab);
    loadPage(DEFAULT_PAGE[tab]);
  }

  // Top nav tab clicks
  document.querySelectorAll('.top-link[data-tab]').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      switchTab(link.dataset.tab);
    });
  });

  // Copy button
  document.getElementById('copy-btn').addEventListener('click', () => {
    navigator.clipboard.writeText(window.location.href);
    const btn = document.getElementById('copy-btn');
    const orig = btn.innerHTML;
    btn.innerHTML = 'Copied! <span>✓</span>';
    setTimeout(() => { btn.innerHTML = orig; }, 2000);
  });

  // Theme Toggle
  const toggleBtn = document.getElementById('theme-toggle');
  const themeIcon = document.querySelector('.theme-icon');
  function setTheme(theme) {
    document.body.setAttribute('data-theme', theme);
    if (theme === 'light') {
      themeIcon.innerHTML = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>';
      themeIcon.style.stroke = '#f59e0b';
    } else {
      themeIcon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
      themeIcon.style.stroke = 'var(--bg)';
    }
  }
  toggleBtn.addEventListener('click', () => {
    setTheme(document.body.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  });

  // Init — start on policies tab with privacy page
  buildSidebar('policies');
  loadPage('privacy');
})();