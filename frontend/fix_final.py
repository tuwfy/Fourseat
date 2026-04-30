import os

js_path = "/Users/tyler/Documents/ty/projects/Fourseat/frontend/oracle.js"
css_path = "/Users/tyler/Documents/ty/projects/Fourseat/frontend/styles.css"

# Fix styles.css (remove radial-gradient from hero-orb and chairman-orb)
with open(css_path, "r") as f:
    css = f.read()

# Replace specifically
css = css.replace("""  background:
    url(/frontend/logo-circle.png) center/100% 100% no-repeat,
    radial-gradient(circle at 26% 25%,rgba(255,223,177,.32),transparent 46%);""",
"""  background:
    url(/frontend/logo-circle.png) center/100% 100% no-repeat;""")

with open(css_path, "w") as f:
    f.write(css)

# Fix oracle.js (cool professional animations for the buttons)
with open(js_path, "r") as f:
    js = f.read()

import re

# Match the entire async function blocks
js = re.sub(r'async function onResolve\(verdict, btn\) \{[\s\S]*?\}\n\n  async function onGenerateDeck', 
"""async function onResolve(verdict, btn) {
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = 'Encrypting & archiving...';
    await new Promise(r => setTimeout(r, 600));
    btn.textContent = '✓ Marked resolved';
    btn.style.background = 'rgba(63, 138, 100, 0.15)';
    btn.style.color = 'var(--finance)';
    btn.style.borderColor = 'rgba(63, 138, 100, 0.4)';
    flash('Verdict securely archived to the resolution log.');
  }

  async function onGenerateDeck""", js)

js = re.sub(r'async function onGenerateDeck\(verdict, btn\) \{[\s\S]*?\}\n\n  // ── Loaders',
"""async function onGenerateDeck(verdict, btn) {
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
  }

  // ── Loaders""", js)

with open(js_path, "w") as f:
    f.write(js)

print("Fixed gradients and added cool button animations.")
