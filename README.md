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
| `/api/billing/checkout-session` | POST | Create Stripe Checkout session when `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID` are set; otherwise returns success with `billing_available: false` (waitlist-only) |
| `/api/debate` | POST | Run a board debate |
| `/api/memory/upload` | POST | Upload document to BoardMind |
| `/api/memory/query` | POST | Query company memory |
| `/api/memory/documents` | GET | List ingested documents |
| `/api/brief/generate` | POST | Generate board deck |
| `/api/brief/download/<file>` | GET | Download generated deck |

---

## Pricing Ideas (if you ship this)

| Tier | Price | Includes |
|---|---|---|
| Founder | $49/mo | Unlimited debates, 3 doc uploads |
| Growth | $149/mo | Everything + BoardBrief, unlimited docs |
| Studio | $399/mo | Multiple workspaces, team access |

---

Built with Flask · Anthropic · OpenAI · Google AI · ChromaDB · python-pptx
