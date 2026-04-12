#!/usr/bin/env python3
"""
Fourseat - Launcher
Run this file to start the app: python run.py
"""
import os
import sys
from pathlib import Path

# Ensure we're in the right directory
os.chdir(Path(__file__).parent)

# Check for .env
if not Path(".env").exists():
    print("\n⚠️  No .env file found.")
    print("👉  Copy .env.example to .env and fill in your API keys:\n")
    print("    cp .env.example .env\n")
    sys.exit(1)

# Check API keys only if paid mode is enabled
from dotenv import load_dotenv
load_dotenv()

debate_mode = os.getenv("DEBATE_MODE", "free").strip().lower()
if debate_mode == "paid":
    missing = []
    if not os.getenv("ANTHROPIC_API_KEY", "").startswith("sk-"):
        missing.append("ANTHROPIC_API_KEY")
    if not os.getenv("OPENAI_API_KEY", "").startswith("sk-"):
        missing.append("OPENAI_API_KEY")
    if missing:
        print(f"\n⚠️  Missing or invalid API keys in .env: {', '.join(missing)}")
        print("Switch DEBATE_MODE=free to avoid paid API calls.\n")

from app import app

port  = int(os.getenv("PORT", 5000))
debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

print("\n" + "═"*50)
print("  🎯  Fourseat")
print("═"*50)
print(f"  → http://localhost:{port}")
print(f"  → Boardroom: http://localhost:{port}/#debate")
print(f"  → Fourseat Memory:  http://localhost:{port}/#memory")
print(f"  → Fourseat Decks: http://localhost:{port}/#brief")
print(f"  → Debate mode: {debate_mode}")
print("═"*50 + "\n")

app.run(host="0.0.0.0", port=port, debug=debug)
