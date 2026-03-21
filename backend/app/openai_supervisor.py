"""
Gen 4 AI supervisor: one OpenAI call with market snapshot + news context.
Returns: decision (allow / limit / block), reasoning (plain English), and optional guidance.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.lab_settings import get_api_keys


SUPERVISOR_SYSTEM = """You are a cautious crypto trading supervisor. You do NOT place trades yourself.
You review market data and news and decide whether the trading bot should be ALLOWED, LIMITED, or BLOCKED.

Decision rules (apply strictly):
- ALLOW only when conditions are relatively stable or favorable: small moves, no broad selloff, no clearly negative news. Use "allow" sparingly.
- LIMIT when there is moderate weakness, mixed conditions, or uncertain news. Reduce risk: smaller positions, fewer new buys.
- BLOCK when there is broad market weakness, sharp declines across symbols, or clearly negative headlines. No new buys this cycle.

Important:
- If there is no supportive or positive news, do NOT assume recovery. Prefer limit or block when the market summary shows weakness.
- When in doubt between two options, prefer the more protective one (e.g. limit over allow, block over limit).

Reply with ONLY a valid JSON object, no other text. Example:
{"decision": "allow", "reasoning": "Stable, small moves, no concerning news.", "guidance": "Normal rules."}
{"decision": "limit", "reasoning": "Moderate weakness or mixed signals.", "guidance": "Reduce position sizes."}
{"decision": "block", "reasoning": "Broad weakness or sharp decline; negative news.", "guidance": "No new buys."}

Allowed values for "decision": allow, limit, block.
Keep "reasoning" and "guidance" to 1-2 short sentences each."""


async def get_supervisor_decision(market_summary: str, news_context: str) -> dict[str, Any]:
    """
    Returns {"decision": "allow"|"limit"|"block", "reasoning": "...", "guidance": "..."}.
    On API error or missing key, returns limit (conservative fallback).
    """
    api_key = get_api_keys().get("openai_api_key") or ""
    if not api_key or api_key == "***":
        return {
            "decision": "limit",
            "reasoning": "OpenAI API key not configured; supervisor defaulting to limit (conservative).",
            "guidance": "Configure API key in Settings for AI supervision.",
            "source": "fallback",
        }

    user_content = f"Market: {market_summary}\n\nNews: {news_context}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": SUPERVISOR_SYSTEM},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 200,
                    "temperature": 0.3,
                },
            )
            if r.status_code != 200:
                return {
                    "decision": "limit",
                    "reasoning": f"OpenAI API error: {r.status_code}. Defaulting to limit (conservative).",
                    "guidance": "Check API key and quota.",
                    "source": "fallback",
                }
            data = r.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "{}")
    except Exception as e:
        return {
            "decision": "limit",
            "reasoning": f"Supervisor request failed: {e}. Defaulting to limit (conservative).",
            "guidance": "Check network and API key.",
            "source": "fallback",
        }

    try:
        # Strip markdown code block if present
        if "```" in content:
            content = content.split("```")[1].replace("json", "").strip()
        out = json.loads(content)
        decision = (out.get("decision") or "limit").lower()
        if decision not in ("allow", "limit", "block"):
            decision = "limit"
        return {
            "decision": decision,
            "reasoning": out.get("reasoning", "No reasoning provided."),
            "guidance": out.get("guidance", ""),
            "source": "api",
        }
    except Exception:
        return {
            "decision": "limit",
            "reasoning": "Could not parse supervisor response. Defaulting to limit (conservative).",
            "guidance": "",
            "source": "fallback",
        }
