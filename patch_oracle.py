import re

with open("frontend/oracle.js", "r") as f:
    js = f.read()

new_html = """
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
"""

# Regex replacement
pattern = re.compile(r"// Build fake chart bars.*slideFrame\.innerHTML\s*=\s*`.*?`;", re.DOTALL)
js = pattern.sub(new_html.strip(), js)

with open("frontend/oracle.js", "r") as f:
    old_js = f.read()

if old_js != js:
    with open("frontend/oracle.js", "w") as f:
        f.write(js)
    print("oracle.js successfully patched!")
else:
    print("oracle.js was not changed. Regex might have failed.")
