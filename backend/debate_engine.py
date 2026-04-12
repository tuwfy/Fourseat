"""
Fourseat - Debate Engine
Supports free local mode (default) and optional paid API mode.
"""

import os
import json
import time
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv():
        return None

load_dotenv()

DEBATE_MODE = os.getenv("DEBATE_MODE", "free").strip().lower()


# ── Individual AI board members ───────────────────────────────────────────────

def _ask_openai_compatible(
    *,
    prompt: str,
    system: str,
    model: str,
    api_key: str,
    base_url: str,
    provider_name: str,
) -> str:
    try:
        import openai

        client = openai.OpenAI(api_key=api_key, base_url=base_url.rstrip("/"))
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as exc:
        return f"[{provider_name} unavailable: {exc}]"


def ask_claude(prompt: str, system: str = "", model: str = "claude-3-haiku-20240307") -> str:
    nia_key = os.getenv("NIA_API_KEY", "").strip()
    if nia_key:
        return _ask_openai_compatible(
            prompt=prompt,
            system=system,
            model=os.getenv("NIA_MODEL", "nia-1"),
            api_key=nia_key,
            base_url=os.getenv("NIA_BASE_URL", "https://api.nia.ai/v1"),
            provider_name="Nia.ai",
        )

    try:
        import anthropic
        anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        messages = [{"role": "user", "content": prompt}]
        kwargs = {"model": model, "max_tokens": 1024, "messages": messages}
        if system:
            kwargs["system"] = system
        response = anthropic_client.messages.create(**kwargs)
        return response.content[0].text
    except Exception as e:
        return f"[Claude unavailable: {e}]"


def ask_gpt4(prompt: str, system: str = "") -> str:
    cerebras_key = os.getenv("CEREBRAS_API_KEY", "").strip()
    if cerebras_key:
        return _ask_openai_compatible(
            prompt=prompt,
            system=system,
            model=os.getenv("CEREBRAS_MODEL", "llama3.1-70b"),
            api_key=cerebras_key,
            base_url=os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"),
            provider_name="Cerebras",
        )

    try:
        import openai
        openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
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
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if nvidia_key:
        return _ask_openai_compatible(
            prompt=prompt,
            system=system,
            model=os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"),
            api_key=nvidia_key,
            base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            provider_name="NVIDIA",
        )

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY", ""))
        model = genai.GenerativeModel("gemini-1.5-flash")
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"[Gemini unavailable: {e}]"


# ── Board member personas ─────────────────────────────────────────────────────

BOARD_PERSONAS = {
    "claude": {
        "role": "Chief Strategy Officer",
        "ai": "Nia.ai",
        "focus": "long-term strategy, ethics, risk, and second-order consequences",
        "system": (
            "You are a seasoned Chief Strategy Officer on a board of directors. "
            "You focus on long-term strategy, ethical implications, and second-order consequences. "
            "You are thoughtful, nuanced, and always consider how decisions affect all stakeholders. "
            "Be direct, opinionated, and concise. Max 200 words."
        ),
    },
    "gpt4": {
        "role": "Chief Financial Officer",
        "ai": "Cerebras",
        "focus": "financial risk, unit economics, market dynamics, and ROI",
        "system": (
            "You are a sharp CFO on a board of directors. "
            "You focus on financial risk, unit economics, burn rate, market sizing, and ROI. "
            "You challenge assumptions with data. You are skeptical of optimism without numbers. "
            "Be direct, numbers-focused, and concise. Max 200 words."
        ),
    },
    "gemini": {
        "role": "Chief Technology Officer",
        "ai": "NVIDIA",
        "focus": "technical feasibility, competitive landscape, and data-driven insights",
        "system": (
            "You are a technical CTO on a board of directors. "
            "You focus on technical feasibility, scalability, competitive landscape, and data. "
            "You look at what the market data says and what competitors are doing. "
            "Be analytical, precise, and concise. Max 200 words."
        ),
    },
    "contrarian": {
        "role": "Independent Contrarian Board Member",
        "ai": "Free Contrarian Model",
        "focus": "devil's advocate, stress-testing assumptions, and finding fatal flaws",
        "system": (
            "You are a contrarian independent board member known for stress-testing ideas. "
            "Your job is to find the fatal flaw, challenge consensus, and voice the uncomfortable truth. "
            "You are not cynical for sport — you genuinely protect founders from blind spots. "
            "Be bold, provocative, and concise. Max 200 words."
        ),
    },
}

CHAIRMAN_SYSTEM = """You are the Board Chair at Fourseat.
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


def _free_role_response(role: str, focus: str, question: str, context: str, debate_view: str = "") -> str:
    context_line = context.strip() or "No extra context provided."
    if debate_view:
        return (
            f"Position ({role}): I challenge the current direction through a {focus} lens.\n"
            f"Key adjustment: The board should tighten assumptions before execution, especially around: {question[:140]}.\n"
            f"What the board missed: convert debate points into measurable checkpoints and a 30-day review trigger."
        )
    return (
        f"Position ({role}): Prioritize decisions through {focus}.\n"
        f"Recommendation: For \"{question[:160]}\", set one clear success metric and one risk guardrail before committing.\n"
        f"Context signal: {context_line[:180]}"
    )


def _free_chairman_summary(question: str, round2: dict) -> dict:
    return {
        "verdict": f"Proceed in staged milestones on: {question[:180]}",
        "confidence": "Medium",
        "key_risks": [
            "Execution complexity is underestimated",
            "Weak measurement can hide failure until late",
            "Resource allocation may dilute core priorities",
        ],
        "key_opportunities": [
            "Faster learning via milestone-based rollout",
            "Clearer board visibility with defined KPIs",
        ],
        "action_steps": [
            "Define success KPI, stop-loss trigger, and owner",
            "Run a 30-day pilot and review outcomes",
            "Scale only if KPI and risk thresholds are met",
        ],
        "dissenting_view": "A decisive all-in move might capture market timing faster than a staged rollout.",
        "best_board_member": "Independent Contrarian Board Member for pressure-testing assumptions early.",
    }


# ── Main debate orchestrator ──────────────────────────────────────────────────

def run_debate(
    question: str,
    context: str = "",
    seat_names: Optional[dict] = None,
    leader_name: str = "",
) -> dict:
    """
    Full Fourseat debate pipeline:
    1. Each board member gives independent analysis
    2. Each member sees the others' views and responds
    3. Chairman synthesizes into final recommendation
    """
    del seat_names  # kept for backward compatibility with older frontend payloads
    personas = BOARD_PERSONAS
    leader = "Board Chair"
    full_question = f"{question}\n\nAdditional context: {context}" if context else question

    # ── Round 1: Independent analysis ────────────────────────────────────────
    round1 = {}

    round1_prompt = (
        f"A founder is asking the board for advice on the following:\n\n"
        f"\"{full_question}\"\n\n"
        f"Give your independent board member perspective on this."
    )

    if DEBATE_MODE == "free":
        round1["claude"] = _free_role_response(personas["claude"]["role"], personas["claude"]["focus"], question, context)
        round1["gpt4"] = _free_role_response(personas["gpt4"]["role"], personas["gpt4"]["focus"], question, context)
        round1["gemini"] = _free_role_response(personas["gemini"]["role"], personas["gemini"]["focus"], question, context)
        round1["contrarian"] = _free_role_response(personas["contrarian"]["role"], personas["contrarian"]["focus"], question, context)
    else:
        round1["claude"] = ask_claude(round1_prompt, personas["claude"]["system"])
        round1["gpt4"] = ask_gpt4(round1_prompt, personas["gpt4"]["system"])
        round1["gemini"] = ask_gemini(round1_prompt, personas["gemini"]["system"])
        round1["contrarian"] = ask_claude(round1_prompt, personas["contrarian"]["system"])

    # ── Round 2: Debate — each sees the others' responses ────────────────────
    debate_context = "\n\n".join([
        f"{personas['claude']['role']}: {round1['claude']}",
        f"{personas['gpt4']['role']}: {round1['gpt4']}",
        f"{personas['gemini']['role']}: {round1['gemini']}",
        f"{personas['contrarian']['role']}: {round1['contrarian']}",
    ])

    round2_prompt = (
        f"The original question was: \"{full_question}\"\n\n"
        f"Here is what your fellow board members said:\n\n{debate_context}\n\n"
        f"Now respond: Do you agree or disagree? What did they miss? "
        f"What's the most important thing the founder needs to hear that hasn't been said? "
        f"Be direct and challenge the group where needed."
    )

    round2 = {}
    if DEBATE_MODE == "free":
        round2["claude"] = _free_role_response(personas["claude"]["role"], personas["claude"]["focus"], question, context, debate_view=debate_context)
        round2["gpt4"] = _free_role_response(personas["gpt4"]["role"], personas["gpt4"]["focus"], question, context, debate_view=debate_context)
        round2["gemini"] = _free_role_response(personas["gemini"]["role"], personas["gemini"]["focus"], question, context, debate_view=debate_context)
        round2["contrarian"] = _free_role_response(personas["contrarian"]["role"], personas["contrarian"]["focus"], question, context, debate_view=debate_context)
    else:
        round2["claude"] = ask_claude(round2_prompt, personas["claude"]["system"])
        round2["gpt4"] = ask_gpt4(round2_prompt, personas["gpt4"]["system"])
        round2["gemini"] = ask_gemini(round2_prompt, personas["gemini"]["system"])
        round2["contrarian"] = ask_claude(round2_prompt, personas["contrarian"]["system"])

    # ── Chairman synthesis ────────────────────────────────────────────────────
    if DEBATE_MODE == "free":
        chairman = _free_chairman_summary(question=question, round2=round2)
    else:
        chairman_prompt = (
            f"Original question: \"{full_question}\"\n\n"
            f"=== ROUND 1: INDEPENDENT VIEWS ===\n{debate_context}\n\n"
            f"=== ROUND 2: DEBATE ===\n"
            + "\n\n".join(
                [
                    f"{personas['claude']['role']} rebuttal: {round2['claude']}",
                    f"{personas['gpt4']['role']} rebuttal: {round2['gpt4']}",
                    f"{personas['gemini']['role']} rebuttal: {round2['gemini']}",
                    f"{personas['contrarian']['role']} rebuttal: {round2['contrarian']}",
                ]
            )
            + f"\n\nNow synthesize the full debate into a final board recommendation from {leader}."
        )
        chairman_raw = ask_claude(chairman_prompt, CHAIRMAN_SYSTEM, model="claude-3-opus-20240229")

        try:
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
        "personas": personas,
        "leader_name": leader,
        "mode": DEBATE_MODE,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
