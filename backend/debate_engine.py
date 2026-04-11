"""
Fourseat - Debate Engine
Orchestrates multi-AI debates, Fourseat Memory memory, and Fourseat Decks deck generation.
"""

import os
import json
import time
from typing import Optional
import anthropic
import openai
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ── API clients ──────────────────────────────────────────────────────────────
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
openai_client    = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
genai.configure(api_key=os.getenv("GOOGLE_API_KEY", ""))


# ── Individual AI board members ───────────────────────────────────────────────

def ask_claude(prompt: str, system: str = "", model: str = "claude-3-haiku-20240307") -> str:
    try:
        messages = [{"role": "user", "content": prompt}]
        kwargs = {"model": model, "max_tokens": 1024, "messages": messages}
        if system:
            kwargs["system"] = system
        response = anthropic_client.messages.create(**kwargs)
        return response.content[0].text
    except Exception as e:
        return f"[Claude unavailable: {e}]"


def ask_gpt4(prompt: str, system: str = "") -> str:
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[GPT-4 unavailable: {e}]"


def ask_gemini(prompt: str, system: str = "") -> str:
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"[Gemini unavailable: {e}]"


# ── Board member personas ─────────────────────────────────────────────────────

BOARD_PERSONAS = {
    "claude": {
        "name": "Alexandra Chen",
        "title": "Chief Strategy Officer",
        "ai": "Claude (Anthropic)",
        "focus": "long-term strategy, ethics, risk, and second-order consequences",
        "color": "#FF6B35",
        "emoji": "🟠",
        "system": (
            "You are Alexandra Chen, a seasoned Chief Strategy Officer on a board of directors. "
            "You focus on long-term strategy, ethical implications, and second-order consequences. "
            "You are thoughtful, nuanced, and always consider how decisions affect all stakeholders. "
            "Be direct, opinionated, and concise. Max 200 words."
        ),
    },
    "gpt4": {
        "name": "Marcus Williams",
        "title": "Chief Financial Officer",
        "ai": "GPT-4 (OpenAI)",
        "focus": "financial risk, unit economics, market dynamics, and ROI",
        "color": "#4CAF50",
        "emoji": "🟢",
        "system": (
            "You are Marcus Williams, a sharp CFO on a board of directors. "
            "You focus on financial risk, unit economics, burn rate, market sizing, and ROI. "
            "You challenge assumptions with data. You are skeptical of optimism without numbers. "
            "Be direct, numbers-focused, and concise. Max 200 words."
        ),
    },
    "gemini": {
        "name": "Priya Patel",
        "title": "Chief Technology Officer",
        "ai": "Gemini (Google)",
        "focus": "technical feasibility, competitive landscape, and data-driven insights",
        "color": "#2196F3",
        "emoji": "🔵",
        "system": (
            "You are Priya Patel, a technical CTO on a board of directors. "
            "You focus on technical feasibility, scalability, competitive landscape, and data. "
            "You look at what the market data says and what competitors are doing. "
            "Be analytical, precise, and concise. Max 200 words."
        ),
    },
    "contrarian": {
        "name": "Viktor Roth",
        "title": "Independent Board Member",
        "ai": "Claude (Contrarian Mode)",
        "focus": "devil's advocate, stress-testing assumptions, and finding fatal flaws",
        "color": "#9C27B0",
        "emoji": "🟣",
        "system": (
            "You are Viktor Roth, a contrarian independent board member known for stress-testing ideas. "
            "Your job is to find the fatal flaw, challenge consensus, and voice the uncomfortable truth. "
            "You are not cynical for sport — you genuinely protect founders from blind spots. "
            "Be bold, provocative, and concise. Max 200 words."
        ),
    },
}

CHAIRMAN_SYSTEM = """You are the Chairman of the Board at Fourseat.
Your job is to synthesize a multi-AI debate into one clear, actionable recommendation for a founder.
Structure your response EXACTLY as valid JSON with these keys:
{
  "verdict": "one sentence bottom line recommendation",
  "confidence": "High / Medium / Low",
  "key_risks": ["risk 1", "risk 2", "risk 3"],
  "key_opportunities": ["opp 1", "opp 2"],
  "action_steps": ["step 1", "step 2", "step 3"],
  "dissenting_view": "the strongest counterargument to your recommendation",
  "best_board_member": "name of board member who gave the most valuable insight and why"
}
Return ONLY the JSON object, no markdown, no extra text."""


# ── Main debate orchestrator ──────────────────────────────────────────────────

def run_debate(question: str, context: str = "") -> dict:
    """
    Full Fourseat debate pipeline:
    1. Each board member gives independent analysis
    2. Each member sees the others' views and responds
    3. Chairman synthesizes into final recommendation
    """
    full_question = f"{question}\n\nAdditional context: {context}" if context else question

    # ── Round 1: Independent analysis ────────────────────────────────────────
    round1 = {}

    round1_prompt = (
        f"A founder is asking the board for advice on the following:\n\n"
        f"\"{full_question}\"\n\n"
        f"Give your independent board member perspective on this."
    )

    round1["claude"]      = ask_claude(round1_prompt,  BOARD_PERSONAS["claude"]["system"])
    round1["gpt4"]        = ask_gpt4(round1_prompt,    BOARD_PERSONAS["gpt4"]["system"])
    round1["gemini"]      = ask_gemini(round1_prompt,  BOARD_PERSONAS["gemini"]["system"])
    round1["contrarian"]  = ask_claude(              # uses claude in contrarian mode
        round1_prompt, BOARD_PERSONAS["contrarian"]["system"]
    )

    # ── Round 2: Debate — each sees the others' responses ────────────────────
    debate_context = "\n\n".join([
        f"Alexandra Chen (Strategy): {round1['claude']}",
        f"Marcus Williams (Finance): {round1['gpt4']}",
        f"Priya Patel (Technology): {round1['gemini']}",
        f"Viktor Roth (Contrarian): {round1['contrarian']}",
    ])

    round2_prompt = (
        f"The original question was: \"{full_question}\"\n\n"
        f"Here is what your fellow board members said:\n\n{debate_context}\n\n"
        f"Now respond: Do you agree or disagree? What did they miss? "
        f"What's the most important thing the founder needs to hear that hasn't been said? "
        f"Be direct and challenge the group where needed."
    )

    round2 = {}
    round2["claude"]      = ask_claude(round2_prompt,  BOARD_PERSONAS["claude"]["system"])
    round2["gpt4"]        = ask_gpt4(round2_prompt,    BOARD_PERSONAS["gpt4"]["system"])
    round2["gemini"]      = ask_gemini(round2_prompt,  BOARD_PERSONAS["gemini"]["system"])
    round2["contrarian"]  = ask_claude(round2_prompt,  BOARD_PERSONAS["contrarian"]["system"])

    # ── Chairman synthesis ────────────────────────────────────────────────────
    chairman_prompt = (
        f"Original question: \"{full_question}\"\n\n"
        f"=== ROUND 1: INDEPENDENT VIEWS ===\n{debate_context}\n\n"
        f"=== ROUND 2: DEBATE ===\n"
        + "\n\n".join([
            f"Alexandra Chen rebuttal: {round2['claude']}",
            f"Marcus Williams rebuttal: {round2['gpt4']}",
            f"Priya Patel rebuttal: {round2['gemini']}",
            f"Viktor Roth rebuttal: {round2['contrarian']}",
        ])
        + f"\n\nNow synthesize the full debate into a final board recommendation."
    )

    chairman_raw = ask_claude(chairman_prompt, CHAIRMAN_SYSTEM, model="claude-3-opus-20240229")

    # parse chairman JSON safely
    try:
        # strip any accidental markdown fences
        clean = chairman_raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        chairman = json.loads(clean)
    except Exception:
        chairman = {
            "verdict": chairman_raw[:300],
            "confidence": "Medium",
            "key_risks": [],
            "key_opportunities": [],
            "action_steps": [],
            "dissenting_view": "",
            "best_board_member": "",
        }

    return {
        "question": question,
        "round1": round1,
        "round2": round2,
        "chairman": chairman,
        "personas": BOARD_PERSONAS,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
