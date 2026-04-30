import re
import os

js_path = "/Users/tyler/Documents/ty/projects/Fourseat/frontend/oracle.js"
html_path = "/Users/tyler/Documents/ty/projects/Fourseat/frontend/oracle.html"

# Fix oracle.js to pass the right object structure to renderSnapshot
with open(js_path, "r") as f:
    js = f.read()

js = js.replace("renderSnapshot(slide.summary, 'demo');", 
                "renderSnapshot({ today: slide.summary, deltas: slide.summary, series: slide.summary.series }, 'demo');")

# Also let's add a fake streaming audit log to the page
log_js = """
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
"""

if "// --- AUDIT LOG STREAM ---" not in js:
    # insert before bootstrap();
    js = js.replace("bootstrap();\n})()", log_js + "\n  bootstrap();\n})()")

with open(js_path, "w") as f:
    f.write(js)

# Now modify oracle.html to add the stream UI and fix oxOrb animation
with open(html_path, "r") as f:
    html = f.read()

html = html.replace("""@keyframes oxOrbFloat{
    0%,100%{transform:translateY(0)}
    50%{transform:translateY(-3px)}
  }
  @keyframes oxOrbSpin{
    from{filter:drop-shadow(0 8px 22px rgba(183,114,66,.32)) hue-rotate(0deg)}
    to{filter:drop-shadow(0 8px 22px rgba(183,114,66,.32)) hue-rotate(8deg)}
  }""", """@keyframes oxOrbFloat{
    0%,100%{translate:0 0}
    50%{translate:0 -4px}
  }
  @keyframes oxOrbSpin{
    from{rotate:0deg}
    to{rotate:360deg}
  }""")

html = html.replace("animation:oxOrbFloat 5s ease-in-out infinite, oxOrbSpin 40s linear infinite;",
                    "animation:oxOrbSpin 10s linear infinite, oxOrbFloat 4s ease-in-out infinite;")

# Add the stream log UI to the HTML
stream_css = """
  .ox-stream {
    margin-top: 1.5rem;
    padding: 1rem;
    background: rgba(0,0,0,0.03);
    border: 1px dashed var(--line-2);
    border-radius: 12px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    color: var(--muted);
    height: 100px;
    overflow: hidden;
    position: relative;
  }
  body[data-theme='dark'] .ox-stream { background: rgba(255,255,255,0.02); }
  .ox-stream::after {
    content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 30px;
    background: linear-gradient(to top, var(--bg), transparent);
  }
  .ox-stream-title { font-weight: 700; color: var(--accent); margin-bottom: 0.5rem; letter-spacing: 0.1em; text-transform: uppercase; }
  .ox-stream ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.3rem; }
  .ox-stream li { animation: oxRiseLeft 0.3s ease-out; }
"""

if ".ox-stream {" not in html:
    html = html.replace("/* ── HERO ─────────────────────────────────────── */", stream_css + "\n  /* ── HERO ─────────────────────────────────────── */")

stream_html = """
      <div class="ox-stream">
        <div class="ox-stream-title">Live Pipeline Stream</div>
        <ul id="ox-stream-list">
          <li>[init] Listening for Stripe events...</li>
        </ul>
      </div>
"""

if "ox-stream" not in html.split("<!-- SNAPSHOT CARD -->")[0]:
    html = html.replace('<div class="ox-flash" id="ox-flash" role="status" aria-live="polite"></div>\n    </div>\n\n    <!-- SNAPSHOT CARD -->',
                        '<div class="ox-flash" id="ox-flash" role="status" aria-live="polite"></div>\n' + stream_html + '\n    </div>\n\n    <!-- SNAPSHOT CARD -->')


with open(html_path, "w") as f:
    f.write(html)

print("Fixed snapshot, added live stream, fixed oracle orb.")
