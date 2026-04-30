import os

js_path = "/Users/tyler/Documents/ty/projects/Fourseat/frontend/oracle.js"
with open(js_path, "r") as f:
    js = f.read()

import re

# Update runScan to have play icon and slower interval
js = re.sub(r"runIcon\.innerHTML = '<span class=\"ox-spinner\" aria-hidden=\"true\"><\/span>';",
            "runIcon.innerHTML = '<svg width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"currentColor\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><polygon points=\"5 3 19 12 5 21 5 3\"/></svg>';", js)

js = re.sub(r"setInterval\(cycleSlide, 6500\)", "setInterval(cycleSlide, 15000)", js)

# Update onResolve to cycle slide
resolve_code = """async function onResolve(verdict, btn) {
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
  }"""
js = re.sub(r'async function onResolve\(verdict, btn\) \{[\s\S]*?flash\(\'Verdict securely archived to the resolution log\.\'\);\n  \}', resolve_code, js)

# Update onGenerateDeck to show preview
deck_code = """async function onGenerateDeck(verdict, btn) {
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
    for(let i=0; i<6; i++){
       const h = 30 + Math.random()*40;
       const color = i === 5 ? 'var(--p0)' : 'var(--finance)';
       const opacity = i === 5 ? '1' : '0.6';
       bars.push(`<div style="width:24px; height:${h}%; background:${color}; opacity:${opacity}; border-radius:2px 2px 0 0;"></div>`);
    }

    slideFrame.innerHTML = `
      <div style="font-family:'Inter', sans-serif; text-align:left;">
        <div style="font-size:0.6rem; color:var(--muted); margin-bottom:0.8rem; text-transform:uppercase; font-weight:700; letter-spacing:0.1em;">Generated Slide 1/6</div>
        <div style="font-weight:600; font-size:1.2rem; color:var(--fg); margin-bottom:0.5rem; font-family:'Playfair Display', serif;">${ruleLabel(verdict.rule)}</div>
        <div style="font-size:0.8rem; color:var(--muted); margin-bottom:1.5rem; line-height:1.4;">${verdict.one_liner}</div>
        <div style="height:100px; background:var(--card-tint); border-radius:4px; display:flex; align-items:flex-end; padding:0 1rem; gap:8px; justify-content:center; border: 1px solid var(--line-2);">
           ${bars.join('')}
        </div>
      </div>
    `;
    ctaWrap.parentNode.appendChild(slideFrame);
  }"""
js = re.sub(r'async function onGenerateDeck\(verdict, btn\) \{[\s\S]*?flash\(\'Board deck successfully generated\. Ready for download\.\'\);\n  \}', deck_code, js)


with open(js_path, "w") as f:
    f.write(js)

print("Updated oracle.js")
