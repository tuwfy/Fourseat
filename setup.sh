#!/bin/bash
# BoardRoom AI - One-click setup
echo ""
echo "════════════════════════════════════"
echo "  BoardRoom AI - Setup"
echo "════════════════════════════════════"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.10+"
    exit 1
fi

echo "✓ Python found: $(python3 --version)"

# Create venv
if [ ! -d "venv" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv venv
fi

# Activate
source venv/bin/activate

# Install deps
echo "→ Installing dependencies..."
pip install -r requirements.txt -q

# Setup .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  Created .env from template."
    echo "   Open .env and fill in your API keys before running."
    echo ""
    echo "   Required keys:"
    echo "   - ANTHROPIC_API_KEY  (from console.anthropic.com)"
    echo "   - OPENAI_API_KEY     (from platform.openai.com)"
    echo "   - GOOGLE_API_KEY     (from aistudio.google.com)"
fi

echo ""
echo "════════════════════════════════════"
echo "  ✅ Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Run: source venv/bin/activate"
echo "  3. Run: python run.py"
echo "════════════════════════════════════"
echo ""
