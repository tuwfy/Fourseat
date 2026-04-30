import os

frontend_dir = "/Users/tyler/Documents/ty/projects/Fourseat/frontend"

help_html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Fourseat Help Center</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Playfair+Display:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #1c1c1c;
      --sidebar: #161616;
      --fg: #f5f5f5;
      --muted: #a1a1aa;
      --border: #333333;
      --accent: #d4a373;
      --toggle-bg: #333;
      --toggle-dot: #888;
      --search-bg: #222;
    }
    
    body[data-theme='light'] {
      --bg: #ffffff;
      --sidebar: #fcfcfc;
      --fg: #111111;
      --muted: #6b7280;
      --border: #e5e7eb;
      --accent: #b77242;
      --toggle-bg: #e5e7eb;
      --toggle-dot: #ffffff;
      --search-bg: #ffffff;
    }
    
    body {
      margin: 0; padding: 0;
      background: var(--bg); color: var(--fg);
      font-family: 'Inter', sans-serif;
      display: flex; height: 100vh; overflow: hidden;
      transition: background 0.3s, color 0.3s;
    }
    a { color: var(--muted); text-decoration: none; cursor: pointer; }
    a:hover { color: var(--fg); }
    
    /* Left Sidebar */
    .sidebar {
      width: 260px; min-width: 260px;
      background: var(--sidebar);
      border-right: 1px solid var(--border);
      display: flex; flex-direction: column;
      height: 100%; overflow-y: auto;
      transition: background 0.3s, border-color 0.3s;
    }
    .sidebar-header {
      padding: 1.5rem;
      display: flex; align-items: center; justify-content: space-between;
    }
    .logo { font-weight: 600; font-size: 1.1rem; color: var(--fg); display:flex; align-items:center; gap:8px;}
    .logo img { height: 20px; }
    
    /* Theme Toggle */
    .theme-toggle {
      width: 44px; height: 24px; background: var(--toggle-bg);
      border-radius: 12px; position: relative; cursor: pointer;
      display: flex; align-items: center; padding: 2px; box-sizing: border-box;
      transition: background 0.3s;
    }
    .theme-dot {
      width: 20px; height: 20px; background: var(--toggle-dot);
      border-radius: 50%; position: absolute; top: 2px; left: 2px;
      transition: transform 0.3s cubic-bezier(0.4, 0.0, 0.2, 1);
      display: flex; align-items: center; justify-content: center;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    body[data-theme='light'] .theme-dot {
      transform: translateX(20px);
    }
    .theme-icon { width: 12px; height: 12px; stroke: var(--bg); stroke-width: 2; fill: none; stroke-linecap: round; stroke-linejoin: round; }
    
    .search-box {
      margin: 0 1.5rem 1.5rem;
      background: var(--search-bg); border: 1px solid var(--border);
      border-radius: 6px; padding: 0.5rem 0.8rem;
      color: var(--muted); font-size: 0.85rem;
      display: flex; align-items: center; justify-content: space-between;
      transition: background 0.3s, border-color 0.3s;
    }
    .nav-section { margin-bottom: 2rem; }
    .nav-title {
      font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
      color: var(--fg); padding: 0 1.5rem; margin-bottom: 0.8rem; font-weight: 600;
    }
    .nav-link {
      display: block; padding: 0.4rem 1.5rem; font-size: 0.85rem;
      color: var(--muted); transition: all 0.2s;
    }
    .nav-link:hover { color: var(--fg); }
    .nav-link.active { color: var(--fg); border-left: 2px solid var(--fg); background: rgba(128,128,128,0.05); }
    
    /* Main Content */
    .main-wrap {
      flex: 1; display: flex; flex-direction: column; height: 100%; overflow-y: auto;
    }
    .top-nav {
      height: 60px; border-bottom: 1px solid var(--border);
      display: flex; align-items: center; padding: 0 2rem; gap: 2rem;
      flex-shrink: 0; transition: border-color 0.3s;
    }
    .top-link {
      font-size: 0.85rem; color: var(--muted); height: 100%;
      display: flex; align-items: center; border-bottom: 2px solid transparent;
    }
    .top-link.active { color: var(--fg); border-bottom-color: var(--fg); }
    
    .content-area {
      display: flex; padding: 3rem; max-width: 1200px; margin: 0 auto; width: 100%; box-sizing: border-box;
    }
    .content-main { flex: 1; max-width: 700px; }
    
    .breadcrumb { font-size: 0.85rem; color: var(--muted); margin-bottom: 1rem; }
    .page-title { font-family: 'Playfair Display', serif; font-size: 2.5rem; margin: 0 0 2rem; color: var(--fg); }
    
    .prose p { color: var(--muted); line-height: 1.6; font-size: 0.95rem; margin-bottom: 1.5rem; }
    .prose h3 { color: var(--fg); font-size: 1.1rem; margin: 2rem 0 1rem; font-weight: 600;}
    .prose h4 { color: var(--fg); font-size: 1rem; margin: 1.5rem 0 0.5rem; font-weight: 600;}
    .prose strong { color: var(--fg); }
    .prose ul { padding-left: 1.2rem; margin-bottom: 1.5rem; }
    .prose li { color: var(--muted); margin-bottom: 0.5rem; line-height: 1.5; font-size: 0.95rem; }
    .prose a { color: var(--fg); text-decoration: underline; text-decoration-color: var(--border); }
    .prose a:hover { text-decoration-color: var(--fg); }
    
    /* Right TOC */
    .toc { width: 220px; margin-left: 4rem; position: sticky; top: 3rem; height: fit-content; }
    .toc-title { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--fg); margin-bottom: 1rem; font-weight: 600; }
    .toc-inner { border-left: 1px solid var(--border); padding-left: 1rem; transition: border-color 0.3s; }
    .toc-link { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.6rem; }
    .toc-link:hover { color: var(--fg); }
    
    .copy-btn {
      float: right; background: transparent; border: 1px solid var(--border);
      color: var(--muted); padding: 0.4rem 0.8rem; border-radius: 6px; font-size: 0.8rem;
      cursor: pointer; display: flex; align-items: center; gap: 6px;
      transition: background 0.2s, border-color 0.3s;
    }
    .copy-btn:hover { background: rgba(128,128,128,0.1); color: var(--fg); }
    
    @media (max-width: 900px) {
      .toc { display: none; }
      .content-area { padding: 2rem 1.5rem; }
    }
    @media (max-width: 768px) {
      .sidebar { display: none; }
      .top-nav { padding: 0 1.5rem; }
    }
  </style>
</head>
<body data-theme="dark">

  <!-- Left Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-header">
      <div class="logo">
        <img src="/frontend/logo-circle.png" alt="Fourseat"> Fourseat
      </div>
      <!-- Theme Toggle -->
      <div class="theme-toggle" id="theme-toggle" aria-label="Toggle Theme">
        <div class="theme-dot" id="theme-dot">
          <svg class="theme-icon moon-icon" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>
        </div>
      </div>
    </div>
    
    <div class="search-box">
      <span>Search...</span>
      <span style="border:1px solid var(--border); padding:2px 4px; border-radius:4px; font-size:0.7rem;">⌘K</span>
    </div>
    
    <div class="nav-section">
      <div class="nav-title">Terms of Service</div>
      <a class="nav-link" data-page="platform-tos">Platform Terms of Service</a>
      <a class="nav-link" data-page="app-tos">Application Terms of Service</a>
      <a class="nav-link" data-page="user-tos">User Terms of Service</a>
      <a class="nav-link" data-page="vdp">Vulnerability Disclosure Policy</a>
    </div>
    
    <div class="nav-section">
      <div class="nav-title">Policies</div>
      <a class="nav-link active" data-page="privacy">Privacy Policy</a>
      <a class="nav-link" data-page="dpa">Data Processing Addendum</a>
      <a class="nav-link" data-page="copyright">Copyright Dispute Policy</a>
    </div>
    
    <div class="nav-section">
      <div class="nav-title">Security Reports</div>
      <a class="nav-link" data-page="pm-api">Post-Mortem: API Key Exposure</a>
      <a class="nav-link" data-page="pm-workspace">Post-Mortem: Workspace Auto-Join</a>
      <a class="nav-link" data-page="pm-logout">Post-Mortem: Session Logout</a>
    </div>
  </aside>

  <!-- Main Content -->
  <div class="main-wrap">
    <header class="top-nav">
      <a href="/" class="top-link">← Back to Fourseat</a>
      <a class="top-link">Help Center</a>
      <a class="top-link">Fourseat API</a>
      <a class="top-link active">Policies & Documents</a>
    </header>
    
    <div class="content-area">
      <main class="content-main">
        <div class="breadcrumb" id="bc">Policies</div>
        
        <button class="copy-btn" id="copy-btn">Copy page <span>↓</span></button>
        <h1 class="page-title" id="p-title">Privacy Policy</h1>
        
        <div class="prose" id="p-content">
          <!-- Content injected here -->
        </div>
      </main>
      
      <aside class="toc">
        <div class="toc-title">On this page</div>
        <div class="toc-inner" id="toc-list">
          <!-- TOC injected here -->
        </div>
      </aside>
    </div>
  </div>

  <script>
    // --- Data Store ---
    const PAGES = {
      "platform-tos": {
        breadcrumb: "Terms of Service",
        title: "Platform Terms of Service",
        content: `
          <p>These Platform Terms of Service govern your access to the Fourseat API and core infrastructure. <strong>By utilizing the Fourseat API or related developer tools, you agree to adhere strictly to these guidelines.</strong></p>
          <h3>1) Usage Limits and Quotas</h3>
          <p>API requests are subject to strict rate limits to ensure stability across all workspaces. Standard tiers allow up to 1,000 requests per minute. Exceeding these limits will result in HTTP 429 Too Many Requests responses.</p>
          <h3>2) Data Ingestion Requirements</h3>
          <p>You must not submit Personally Identifiable Information (PII) to non-PII compliance endpoints. All data submitted via the API must be sanitized according to your organization's compliance standards.</p>
          <h3>3) SLA and Uptime</h3>
          <p>Fourseat guarantees 99.9% uptime for Enterprise customers. Scheduled maintenance windows will be communicated 48 hours in advance via the status page.</p>
          <h3>4) Termination</h3>
          <p>We reserve the right to suspend API access immediately if we detect malicious activity, reverse engineering, or unauthorized data scraping operations.</p>
        `,
        toc: ["Usage Limits and Quotas", "Data Ingestion Requirements", "SLA and Uptime", "Termination"]
      },
      "app-tos": {
        breadcrumb: "Terms of Service",
        title: "Application Terms of Service",
        content: `
          <p>These Application Terms apply specifically to the Fourseat Web Dashboard and End-User interfaces.</p>
          <h3>1) Account Security</h3>
          <p>You are responsible for maintaining the security of your credentials. Fourseat highly recommends enabling Multi-Factor Authentication (MFA) for all users with access to financial verdicts.</p>
          <h3>2) Output Ownership</h3>
          <p>You retain full ownership of all board decks, PDF exports, and verdicts generated by your workspace. Fourseat claims no intellectual property rights over the AI-synthesized outputs based on your data.</p>
          <h3>3) Acceptable Use</h3>
          <p>You agree not to use the Fourseat application to process illegal transactions, harass individuals, or circumvent regional compliance laws.</p>
        `,
        toc: ["Account Security", "Output Ownership", "Acceptable Use"]
      },
      "user-tos": {
        breadcrumb: "Terms of Service",
        title: "User Terms of Service",
        content: `
          <p>By registering for a Fourseat account, you (the Individual User) agree to these terms.</p>
          <p>Users must be at least 18 years of age. You agree to provide accurate registration information. Fourseat is a decision-support tool, and its outputs (such as legal or financial summaries) should not replace professional counsel.</p>
        `,
        toc: []
      },
      "vdp": {
        breadcrumb: "Terms of Service",
        title: "Vulnerability Disclosure Policy",
        content: `
          <p>Fourseat is committed to ensuring the security of our customers' data. We welcome responsible disclosure of security vulnerabilities.</p>
          <h3>1) Scope</h3>
          <p>Our primary application (fourseat.dev) and API endpoints are in scope. Third-party services (like Stripe) are out of scope.</p>
          <h3>2) Safe Harbor</h3>
          <p>If you conduct security research in good faith and comply with this policy, we consider your actions authorized and will not pursue legal action.</p>
          <h3>3) Reporting</h3>
          <p>Please submit detailed reports to security@fourseat.dev. We aim to acknowledge reports within 24 hours.</p>
        `,
        toc: ["Scope", "Safe Harbor", "Reporting"]
      },
      "privacy": {
        breadcrumb: "Policies",
        title: "Privacy Policy",
        content: `
          <p>At Fourseat, we take your privacy seriously. Please read this Privacy Policy to learn how we treat your personal data. <strong>By using or accessing our Services in any manner, you acknowledge that you accept the practices and policies outlined below.</strong></p>
          <p>Before we get into the details, below are a few key points we'd like you to know:</p>
          <ul>
            <li>We do not allow third parties such as OpenAI or Anthropic to use your Personal Data to train AI models.</li>
            <li>We only use De-Identified Data to train AI models, <a href="#">which you can opt-out of within your account settings</a>.</li>
            <li>We store your Personal Data in AWS servers located in the U.S. All Personal Data is encrypted at rest and in transit.</li>
          </ul>
          <h3>1) Data we collect</h3>
          <p>We collect account/contact details, waitlist submissions, user inputs, uploaded files, and basic operational logs.</p>
          <h3>2) How we use data</h3>
          <p>We use data to provide core product functions, improve reliability, detect abuse, and communicate account updates.</p>
          <h3>3) Processors and vendors</h3>
          <p>We use infrastructure and AI providers (such as Vercel, AWS, OpenAI, and Anthropic) to process requests needed for service delivery.</p>
          <h3>4) Security</h3>
          <p>Fourseat applies encryption in transit, strict access controls, request validation, rate limiting, and hardened security headers.</p>
          <h3>5) Retention and deletion</h3>
          <p>We retain data as needed for service operation and legal obligations. You can request full data deletion by emailing <a href="mailto:hello@fourseat.dev">hello@fourseat.dev</a>.</p>
          <h3>6) Your rights</h3>
          <p>Depending on your location, you may have rights to access, correct, export, or delete your data under GDPR, CCPA, or other regional privacy laws.</p>
        `,
        toc: ["Data we collect", "How we use data", "Processors and vendors", "Security", "Retention and deletion", "Your rights"]
      },
      "dpa": {
        breadcrumb: "Policies",
        title: "Data Processing Addendum",
        content: `
          <p>This DPA supplements the Terms of Service when Fourseat processes personal data subject to the GDPR or CCPA on your behalf.</p>
          <h3>1) Processing Instructions</h3>
          <p>Fourseat will only process personal data according to your documented instructions, primarily to provide the service.</p>
          <h3>2) Subprocessors</h3>
          <p>You authorize Fourseat to engage Subprocessors. We will notify you of any intended changes concerning the addition or replacement of Subprocessors.</p>
        `,
        toc: ["Processing Instructions", "Subprocessors"]
      },
      "copyright": {
        breadcrumb: "Policies",
        title: "Copyright Dispute Policy",
        content: `
          <p>Fourseat respects the intellectual property rights of others. We comply with the Digital Millennium Copyright Act (DMCA).</p>
          <p>If you believe that your copyrighted work has been infringed, please send a written notice to dmca@fourseat.dev with the required statutory elements.</p>
        `,
        toc: []
      },
      "pm-api": {
        breadcrumb: "Security Reports",
        title: "Post-Mortem: API Key Exposure",
        content: `
          <p><strong>Date:</strong> February 14, 2026</p>
          <p><strong>Summary:</strong> A non-production API key was inadvertently committed to a public repository for 14 minutes.</p>
          <h3>Impact</h3>
          <p>No customer data was exposed. The exposed key was isolated to a staging environment with zero access to production databases.</p>
          <h3>Root Cause</h3>
          <p>A developer accidentally bypassed our pre-commit hooks that scan for secrets.</p>
          <h3>Resolution</h3>
          <p>The key was revoked within 15 minutes. We have since mandated server-side secret scanning on all pull requests.</p>
        `,
        toc: ["Impact", "Root Cause", "Resolution"]
      },
      "pm-workspace": {
        breadcrumb: "Security Reports",
        title: "Post-Mortem: Workspace Auto-Join",
        content: `
          <p><strong>Date:</strong> January 8, 2026</p>
          <p><strong>Summary:</strong> A bug in the SAML SSO integration allowed users with matching domain names to auto-join workspaces without explicit admin approval.</p>
          <h3>Impact</h3>
          <p>Three enterprise workspaces were affected. No sensitive board verdicts were accessed by unauthorized users.</p>
          <h3>Resolution</h3>
          <p>We hotfixed the SSO flow and implemented a mandatory 'Admin Approval Queue' for all auto-join requests.</p>
        `,
        toc: ["Impact", "Resolution"]
      },
      "pm-logout": {
        breadcrumb: "Security Reports",
        title: "Post-Mortem: Session Logout",
        content: `
          <p><strong>Date:</strong> November 22, 2025</p>
          <p><strong>Summary:</strong> The 'Log out of all devices' button failed to invalidate active JWT tokens on edge servers.</p>
          <h3>Resolution</h3>
          <p>Tokens are now checked against a centralized Redis blocklist on every authenticated request.</p>
        `,
        toc: ["Resolution"]
      }
    };

    // --- State & DOM ---
    const navLinks = document.querySelectorAll('.nav-link');
    const bcEl = document.getElementById('bc');
    const titleEl = document.getElementById('p-title');
    const contentEl = document.getElementById('p-content');
    const tocList = document.getElementById('toc-list');
    
    function loadPage(pageId) {
      const data = PAGES[pageId];
      if (!data) return;
      
      // Update UI
      bcEl.textContent = data.breadcrumb;
      titleEl.textContent = data.title;
      contentEl.innerHTML = data.content;
      
      // Update TOC
      tocList.innerHTML = '';
      if (data.toc && data.toc.length > 0) {
        data.toc.forEach((h, i) => {
          const a = document.createElement('a');
          a.className = 'toc-link';
          a.href = '#';
          a.textContent = h;
          if (i === 0) a.style.color = 'var(--fg)';
          tocList.appendChild(a);
        });
      } else {
        tocList.innerHTML = '<span style="color:var(--muted); font-size:0.85rem;">No sections</span>';
      }
      
      // Update Active Link
      navLinks.forEach(l => {
        if (l.dataset.page === pageId) l.classList.add('active');
        else l.classList.remove('active');
      });
      
      // Update Top Nav
      document.querySelectorAll('.top-link').forEach(l => l.classList.remove('active'));
      if (data.breadcrumb === 'Terms of Service' || data.breadcrumb === 'Policies') {
        document.querySelectorAll('.top-link')[3].classList.add('active'); // Policies
      } else {
        document.querySelectorAll('.top-link')[1].classList.add('active'); // Help Center
      }
      
      // Scroll top
      document.querySelector('.main-wrap').scrollTop = 0;
    }

    // --- Events ---
    navLinks.forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        loadPage(link.dataset.page);
      });
    });

    document.getElementById('copy-btn').addEventListener('click', () => {
      navigator.clipboard.writeText(window.location.href);
      const btn = document.getElementById('copy-btn');
      const orig = btn.innerHTML;
      btn.innerHTML = 'Copied! <span>✓</span>';
      setTimeout(() => { btn.innerHTML = orig; }, 2000);
    });

    // Theme Toggle Logic
    const toggleBtn = document.getElementById('theme-toggle');
    const themeIcon = document.querySelector('.theme-icon');
    
    // Moon SVG path
    const moonPath = "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z";
    // Sun SVG path
    const sunPath = "M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z";
    
    function setTheme(theme) {
      document.body.setAttribute('data-theme', theme);
      if (theme === 'light') {
        themeIcon.innerHTML = `<path d="${sunPath}"></path>`;
        themeIcon.style.stroke = "#f59e0b"; // orange/sun color
      } else {
        themeIcon.innerHTML = `<path d="${moonPath}"></path>`;
        themeIcon.style.stroke = "var(--bg)"; // dark
      }
    }

    toggleBtn.addEventListener('click', () => {
      const current = document.body.getAttribute('data-theme');
      setTheme(current === 'dark' ? 'light' : 'dark');
    });

    // Init
    loadPage('privacy');
  </script>
</body>
</html>
"""

with open(os.path.join(frontend_dir, "help.html"), "w") as f:
    f.write(help_html)

print("help.html successfully upgraded to SPA with theme toggle and content.")
