# 🎯 BoardRoom AI

**Your personal AI board of directors.**

Four AIs debate your decisions. One AI remembers your entire company history. One AI builds your board deck automatically.

---

## What's Inside

| Module | What it does |
|---|---|
| 🎙 **The Boardroom** | Ask any question. Claude, GPT-4, Gemini, and a Contrarian AI debate it. A Chairman AI delivers the final verdict. |
| 🧠 **BoardMind** | Upload board decks, investor updates, and memos. Query your entire company history in plain English. |
| 📊 **BoardBrief** | Enter your metrics. Get a polished PowerPoint board deck generated in seconds. |

---

## Quick Start

### 1. Get API Keys
- **Anthropic (Claude):** https://console.anthropic.com
- **OpenAI (GPT-4):** https://platform.openai.com
- **Google (Gemini):** https://aistudio.google.com

### 2. Setup

```bash
# Run the setup script
chmod +x setup.sh
./setup.sh

# OR manually:
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. Add API Keys

Edit `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AI...
```

### 4. Run

```bash
source venv/bin/activate
python run.py
```

Open http://localhost:5000

---

## Project Structure

```
boardroom_ai/
├── app.py                  # Flask server & API routes
├── run.py                  # Launcher with startup checks
├── setup.sh                # One-click setup script
├── requirements.txt
├── .env.example
├── backend/
│   ├── debate_engine.py    # Multi-AI debate orchestrator
│   ├── board_mind.py       # Vector memory & document ingestion
│   └── board_brief.py      # PowerPoint deck generator
├── frontend/
│   └── index.html          # Full web UI
└── data/
    ├── uploads/            # Uploaded documents
    ├── memory/             # ChromaDB vector store
    └── outputs/            # Generated decks
```

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/waitlist` | POST | Add a waitlist entry and send confirmation emails |
| `/api/waitlist/count` | GET | Public signup count (used on the waitlist page) |
| `/api/billing/checkout-session` | POST | Create Stripe Checkout session when `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID` are set; otherwise returns success with `billing_available: false` (waitlist-only) |
| `/api/debate` | POST | Run a board debate |
| `/api/memory/upload` | POST | Upload document to BoardMind |
| `/api/memory/query` | POST | Query company memory |
| `/api/memory/documents` | GET | List ingested documents |
| `/api/brief/generate` | POST | Generate board deck |
| `/api/brief/download/<file>` | GET | Download generated deck |
| `/api/sentinel/run` | POST | Fetch inbound, triage with the 4-advisor panel, persist verdicts |
| `/api/sentinel/queue` | GET | Open triage queue + counts per priority |
| `/api/sentinel/brief` | GET | Markdown Daily Decision Briefing |
| `/api/sentinel/resolve` | POST | Mark a triage row resolved |
| `/api/admin/waitlist` | GET | Admin dashboard data (Bearer `FOURSEAT_ADMIN_TOKEN`) |
| `/api/admin/waitlist.csv` | GET | CSV export of all signups |

---

## Waitlist emails (real delivery)

The waitlist supports two delivery paths; the first one configured wins.

### Option A: Resend (recommended on Vercel)

```
RESEND_API_KEY=re_...
SMTP_FROM_EMAIL=hello@yourdomain.com      # verified sender in Resend
SMTP_FROM_NAME=Fourseat
WAITLIST_OWNER_EMAIL=you@yourdomain.com   # owner gets a ping on every new signup
```

### Option B: SMTP (Gmail, Postmark, SES, Mailgun, etc.)

```
SMTP_HOST=smtp.resend.com                 # or smtp.gmail.com, email-smtp.us-east-1.amazonaws.com, ...
SMTP_PORT=587
SMTP_USERNAME=apikey                      # provider-specific
SMTP_PASSWORD=***
SMTP_USE_TLS=true
SMTP_FROM_EMAIL=hello@yourdomain.com
SMTP_FROM_NAME=Fourseat
WAITLIST_OWNER_EMAIL=you@yourdomain.com
```

## Tracking signups

- Every signup is appended to `data/waitlist/waitlist.jsonl` locally and mirrored to Vercel Blob when `BLOB_READ_WRITE_TOKEN` is set (so the list survives cold starts on serverless).
- Public signup counter: `GET /api/waitlist/count`.
- Admin dashboard: `/admin` — set `FOURSEAT_ADMIN_TOKEN` and visit `/admin?token=...` to see live signups + CSV export.

## Sentinel setup

- **Demo mode (default when `GMAIL_CREDS_PATH` is not present):** uses seeded demo emails so you can click **Run Sentinel** on the live site and see a full briefing.
- **Gmail OAuth:** drop `gmail_credentials.json` (OAuth desktop client) into `data/sentinel/` and run the CLI once to authorize: `python -m backend.sentinel`.
- **AI verdicts:** at least one of `NIA_API_KEY`, `ANTHROPIC_API_KEY`, `CEREBRAS_API_KEY`, `OPENAI_API_KEY`, `NVIDIA_API_KEY`, `GOOGLE_API_KEY` enables live LLM verdicts. Without any keys the pipeline still completes with a safe fallback verdict so the dashboard keeps working.

## Legal pages

- Terms of service: `/terms` (or `/tos`)
- Privacy policy: `/privacy`
- Footer links now expose Product / Resources / Company columns for public trust and store-review checks.

## App Store / Google Play readiness

This release includes web installability basics:
- `manifest.webmanifest` with standalone display mode and app icons
- `icon-192.png` and `icon-512.png` assets
- `sw.js` service worker registration (minimal installability worker)
- Hardened production headers (CSP, HSTS, frame deny, permissions policy, origin agent cluster)

Manual steps still required for **native store submission**:
- Wrap the web app in Capacitor/React Native/Flutter shell for iOS/Android binaries
- Add native app screenshots, age rating, content declarations, and support URL
- Provide App Store Connect and Play Console metadata + review credentials
- Configure Apple Sign In / Google Sign In if account auth is required

---

## Pricing Ideas (if you ship this)

| Tier | Price | Includes |
|---|---|---|
| Founder | $49/mo | Unlimited debates, 3 doc uploads |
| Growth | $149/mo | Everything + BoardBrief, unlimited docs |
| Studio | $399/mo | Multiple workspaces, team access |

---

Built with Flask · Anthropic · OpenAI · Google AI · ChromaDB · python-pptx

## Launch Readiness

- For multi-channel launch execution, use `LAUNCH_DAY_PLAYBOOK.md` (Product Hunt, Hacker News, Indie Hackers, AppSumo, G2, and Capterra).
