import json

with open("/Users/tyler/Documents/ty/projects/Fourseat/frontend/oracle.js", "r") as f:
    js = f.read()

# We want to replace from `async function runScan() {` up to the end of the file before `})();`
start_idx = js.find("async function runScan() {")
end_idx = js.rfind("})();")

slides = [
  {
    "summary": { "snapshot_date": "2026-04-30 14:00 UTC", "mrr_cents": 14200000, "mrr_d7_pct": 1.2, "nrr_pct": 104.2, "nrr_d7_delta": -1.4, "active_subs": 1240, "top_customer_share": 0.12, "failed_payments_cents": 450000, "failed_payments_count": 14, "series": [{"mrr_cents": 14000000}, {"mrr_cents": 14100000}, {"mrr_cents": 14200000}] },
    "verdict": {
      "id": 'v1', "rule": 'churn_cluster', "priority": 'P0', "confidence": 'High', "resolved": False,
      "one_liner": 'A concentrated churn cluster just appeared in your $500-$2k ARR segment.',
      "strategy_view": 'A 3x churn spike in one segment is a positioning signal, not a retention problem.',
      "finance_view": 'If this rate continues, you\'ll lose roughly one quarter\'s worth of NRR by month-end.',
      "tech_view": 'Cross-reference cancellation events against the last 14 days of releases.',
      "contrarian_view": 'Maybe this is healthy churn and you\'re shedding the wrong ICP. Accelerate it.',
      "evidence": { "ratio": 3.3 }, "actions": ['Pull churned customer list', 'Pause non-critical pricing changes'],
      "watch_metrics": ['Churn rate by ARR segment']
    }
  },
  {
    "summary": { "snapshot_date": "2026-04-30 14:15 UTC", "mrr_cents": 8900000, "mrr_d7_pct": -0.4, "nrr_pct": 98.1, "nrr_d7_delta": -2.1, "active_subs": 890, "top_customer_share": 0.25, "failed_payments_cents": 120000, "failed_payments_count": 4, "series": [{"mrr_cents": 9000000}, {"mrr_cents": 8950000}, {"mrr_cents": 8900000}] },
    "verdict": {
      "id": 'v2', "rule": 'nrr_drop', "priority": 'P1', "confidence": 'Medium', "resolved": False,
      "one_liner": 'NRR slipped below 100% for the first time in 6 months.',
      "strategy_view": 'Your expansion engine stalled. Account management needs a new playbook.',
      "finance_view": 'Below 100% NRR means you are now paying to replace revenue, destroying LTV/CAC.',
      "tech_view": 'Look for usage drop-offs in the core feature set over the last 30 days.',
      "contrarian_view": 'This is a natural normalization post-COVID. Don\'t panic, focus on new logos.',
      "evidence": { "current_nrr_pct": 98.1 }, "actions": ['Review top 10 downgrades', 'Launch win-back campaign'],
      "watch_metrics": ['Weekly active users in core features']
    }
  },
  {
    "summary": { "snapshot_date": "2026-04-30 14:30 UTC", "mrr_cents": 21500000, "mrr_d7_pct": 4.5, "nrr_pct": 112.5, "nrr_d7_delta": 2.5, "active_subs": 3100, "top_customer_share": 0.08, "failed_payments_cents": 850000, "failed_payments_count": 32, "series": [{"mrr_cents": 20500000}, {"mrr_cents": 21000000}, {"mrr_cents": 21500000}] },
    "verdict": {
      "id": 'v3', "rule": 'failed_payment_leakage', "priority": 'P0', "confidence": 'High', "resolved": False,
      "one_liner": 'Failed payments are up 4x this week, representing $8,500 of at-risk MRR.',
      "strategy_view": 'This is silent churn. Dunning emails aren\'t enough; we need in-app gating.',
      "finance_view": 'If we recover even 50%, we boost our net MRR growth by 2% this month.',
      "tech_view": 'Stripe API might have declined a batch. Check the webhook logs for routing errors.',
      "contrarian_view": 'Let the bad credit cards fail. Focus on enterprise clients who pay by invoice.',
      "evidence": { "avg_pct_of_mrr": 3.9 }, "actions": ['Trigger immediate dunning sequence', 'Add in-app payment wall'],
      "watch_metrics": ['Recovery rate over next 7 days']
    }
  },
  {
    "summary": { "snapshot_date": "2026-04-30 14:45 UTC", "mrr_cents": 5500000, "mrr_d7_pct": 8.1, "nrr_pct": 109.2, "nrr_d7_delta": 0.5, "active_subs": 420, "top_customer_share": 0.42, "failed_payments_cents": 15000, "failed_payments_count": 1, "series": [{"mrr_cents": 5100000}, {"mrr_cents": 5300000}, {"mrr_cents": 5500000}] },
    "verdict": {
      "id": 'v4', "rule": 'concentration_risk', "priority": 'P1', "confidence": 'Medium', "resolved": False,
      "one_liner": 'A single enterprise customer now makes up 42% of your total MRR.',
      "strategy_view": 'You are essentially a consulting firm for this one client. Diversify immediately.',
      "finance_view": 'If they churn, the runway gets cut in half. We cannot plan headcount on this.',
      "tech_view": 'Ensure our architecture isn\'t becoming a bespoke monolith for their specific needs.',
      "contrarian_view": 'Lean into it. Build exactly what they want and charge them double next year.',
      "evidence": { "top_share_pct": 42.0 }, "actions": ['Pause custom feature requests', 'Ramp up SMB marketing spend'],
      "watch_metrics": ['New logo acquisition rate']
    }
  },
  {
    "summary": { "snapshot_date": "2026-04-30 15:00 UTC", "mrr_cents": 42000000, "mrr_d7_pct": 0.2, "nrr_pct": 101.1, "nrr_d7_delta": -4.2, "active_subs": 8500, "top_customer_share": 0.03, "failed_payments_cents": 620000, "failed_payments_count": 28, "series": [{"mrr_cents": 41800000}, {"mrr_cents": 41900000}, {"mrr_cents": 42000000}] },
    "verdict": {
      "id": 'v5', "rule": 'expansion_stall', "priority": 'P2', "confidence": 'Low', "resolved": False,
      "one_liner": 'Seat expansion has flatlined across the mid-market cohort for 14 days.',
      "strategy_view": 'The product is sticky, but not viral. We need a better multi-player loop.',
      "finance_view": 'Without expansion, hitting our $10M ARR target requires 30% more top-of-funnel.',
      "tech_view": 'Check if the invite-user flow is broken or experiencing high latency.',
      "contrarian_view": 'They don\'t want to invite teammates. Stop forcing it and raise the base price.',
      "evidence": { "recent_avg_expansion_cents": 12000 }, "actions": ['Audit the invite-team UX', 'Offer a limited-time seat discount'],
      "watch_metrics": ['Invites sent per active user']
    }
  },
  {
    "summary": { "snapshot_date": "2026-04-30 15:15 UTC", "mrr_cents": 18400000, "mrr_d7_pct": -2.5, "nrr_pct": 94.8, "nrr_d7_delta": -3.8, "active_subs": 2100, "top_customer_share": 0.15, "failed_payments_cents": 310000, "failed_payments_count": 11, "series": [{"mrr_cents": 18800000}, {"mrr_cents": 18600000}, {"mrr_cents": 18400000}] },
    "verdict": {
      "id": 'v6', "rule": 'pricing_tier_collapse', "priority": 'P0', "confidence": 'High', "resolved": False,
      "one_liner": 'Pro tier subscriptions dropped 18% following the recent price hike.',
      "strategy_view": 'We found the price ceiling. Roll back or add immediate grandfathered discounts.',
      "finance_view": 'The elasticity is too high. The 20% price bump caused a net loss in ARR.',
      "tech_view": 'Make sure the downgrade button isn\'t overly prominent in the new billing UI.',
      "contrarian_view": 'Good. We shed the price-sensitive users who eat up all our support hours.',
      "evidence": { "tier": "Pro", "drop_pct": 18.2 }, "actions": ['Analyze support ticket volume from churned users', 'Prepare a win-back offer'],
      "watch_metrics": ['Downgrade rate next 7 days']
    }
  },
  {
    "summary": { "snapshot_date": "2026-04-30 15:30 UTC", "mrr_cents": 32000000, "mrr_d7_pct": 5.8, "nrr_pct": 118.2, "nrr_d7_delta": 4.1, "active_subs": 4200, "top_customer_share": 0.05, "failed_payments_cents": 550000, "failed_payments_count": 19, "series": [{"mrr_cents": 30000000}, {"mrr_cents": 31000000}, {"mrr_cents": 32000000}] },
    "verdict": {
      "id": 'v7', "rule": 'churn_cluster', "priority": 'P1', "confidence": 'Medium', "resolved": False,
      "one_liner": 'An unusual cluster of cancellations from EU customers in the past 48 hours.',
      "strategy_view": 'A new competitor might have launched in Europe. Check Twitter and ProductHunt.',
      "finance_view": 'EU is our fastest growing market. We need to plug this hole immediately.',
      "tech_view": 'Our EU data center experienced a 15-minute outage on Tuesday. That is the trigger.',
      "contrarian_view": 'It\'s August. Europe is on vacation. They are just pausing their accounts.',
      "evidence": { "ratio": 2.8 }, "actions": ['Check uptime logs for EU region', 'Send a localized apology email if outage confirmed'],
      "watch_metrics": ['EU cancellations vs US']
    }
  },
  {
    "summary": { "snapshot_date": "2026-04-30 15:45 UTC", "mrr_cents": 7800000, "mrr_d7_pct": 0.8, "nrr_pct": 105.1, "nrr_d7_delta": -0.5, "active_subs": 650, "top_customer_share": 0.18, "failed_payments_cents": 80000, "failed_payments_count": 3, "series": [{"mrr_cents": 7700000}, {"mrr_cents": 7750000}, {"mrr_cents": 7800000}] },
    "verdict": {
      "id": 'v8', "rule": 'nrr_drop', "priority": 'P2', "confidence": 'Low', "resolved": False,
      "one_liner": 'Expansion revenue from the SMB segment is softening.',
      "strategy_view": 'SMBs are tightening budgets. We need to demonstrate hard ROI, not just convenience.',
      "finance_view": 'CAC payback period is stretching from 6 months to 8 months for this cohort.',
      "tech_view": 'They aren\'t hitting the usage limits that trigger upgrades. Check feature adoption.',
      "contrarian_view": 'SMBs are a distraction anyway. Let it soften and move upmarket.',
      "evidence": { "current_nrr_pct": 105.1 }, "actions": ['Analyze usage patterns of SMBs', 'Create an ROI case study'],
      "watch_metrics": ['Time to upgrade for new SMBs']
    }
  },
  {
    "summary": { "snapshot_date": "2026-04-30 16:00 UTC", "mrr_cents": 51500000, "mrr_d7_pct": 12.4, "nrr_pct": 125.6, "nrr_d7_delta": 8.2, "active_subs": 12500, "top_customer_share": 0.02, "failed_payments_cents": 1250000, "failed_payments_count": 45, "series": [{"mrr_cents": 48000000}, {"mrr_cents": 49500000}, {"mrr_cents": 51500000}] },
    "verdict": {
      "id": 'v9', "rule": 'failed_payment_leakage', "priority": 'P1', "confidence": 'High', "resolved": False,
      "one_liner": 'Massive influx of new signups is bringing a high rate of fraudulent card failures.',
      "strategy_view": 'Our marketing went viral, but we are attracting bad actors. Tighten the funnel.',
      "finance_view": 'Stripe dispute fees will eat our margins if we don\'t block these at the gate.',
      "tech_view": 'Enable Stripe Radar immediately and require 3D Secure for high-risk IP addresses.',
      "contrarian_view": 'More top of funnel is always good. The algorithm will eventually sort them out.',
      "evidence": { "avg_pct_of_mrr": 2.4 }, "actions": ['Enable Stripe Radar rules', 'Monitor dispute rates daily'],
      "watch_metrics": ['Failed payments from new accounts']
    }
  },
  {
    "summary": { "snapshot_date": "2026-04-30 16:15 UTC", "mrr_cents": 12000000, "mrr_d7_pct": -5.2, "nrr_pct": 88.5, "nrr_d7_delta": -8.5, "active_subs": 1100, "top_customer_share": 0.35, "failed_payments_cents": 200000, "failed_payments_count": 8, "series": [{"mrr_cents": 12800000}, {"mrr_cents": 12400000}, {"mrr_cents": 12000000}] },
    "verdict": {
      "id": 'v10', "rule": 'concentration_risk', "priority": 'P0', "confidence": 'High', "resolved": False,
      "one_liner": 'Your second largest customer just cancelled, exposing dangerous concentration.',
      "strategy_view": 'This is a red alert. Call the CEO of the churned account immediately.',
      "finance_view": 'We just lost 15% of our MRR in a single day. Revise the quarterly forecast.',
      "tech_view": 'Check if they exported their data before cancelling. Could indicate a move to a competitor.',
      "contrarian_view": 'We were too dependent on them. Now we are forced to build a real business.',
      "evidence": { "top_share_pct": 35.0 }, "actions": ['Schedule post-mortem with the customer', 'Audit features they used most'],
      "watch_metrics": ['Health scores of remaining top 5 customers']
    }
  }
]

slideshow_code = f"""
  // --- SLIDESHOW OVERRIDE ---
  const DEMO_SLIDES = {json.dumps(slides, indent=2)};
  
  let currentSlide = 0;
  let slideInterval = null;

  function cycleSlide() {{
    const slide = DEMO_SLIDES[currentSlide];
    
    // Render snapshot and verdicts
    renderSnapshot(slide.summary, 'demo');
    renderVerdicts([slide.verdict]);
    renderCounters({{ total_open: 1, by_priority: {{ [slide.verdict.priority]: 1 }} }});
    
    currentSlide = (currentSlide + 1) % DEMO_SLIDES.length;
  }}

  async function runScan() {{
    if (runBtn.disabled) return;
    runBtn.disabled = true;
    runLabel.textContent = 'Slideshow Active';
    runIcon.innerHTML = '<span class="ox-spinner" aria-hidden="true"></span>';
    
    cycleSlide();
    if (!slideInterval) {{
      slideInterval = setInterval(cycleSlide, 6500);
    }}
  }}

  if (runBtn) runBtn.addEventListener('click', runScan);

  async function bootstrap() {{
    await loadConnectors();
    runScan();
  }}
  bootstrap();
"""

new_js = js[:start_idx] + slideshow_code + js[end_idx:]

with open("/Users/tyler/Documents/ty/projects/Fourseat/frontend/oracle.js", "w") as f:
    f.write(new_js)

print("Injected slideshow logic correctly.")
