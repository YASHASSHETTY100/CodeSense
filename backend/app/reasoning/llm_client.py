"""LLM client: anthropic/openai when keys configured, else offline deterministic fallback.

Offline mode composes grounded answers purely from retrieved evidence (extractive),
so the system is demoable + testable without API keys and can never hallucinate
beyond the evidence set.
"""
from __future__ import annotations
import json
from app.config import settings


def llm_complete(system: str, user: str) -> str:
    provider = settings.LLM_PROVIDER.lower()
    if provider == "anthropic" and settings.ANTHROPIC_API_KEY:
        import anthropic
        cl = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        m = cl.messages.create(model=settings.LLM_MODEL or "claude-3-5-sonnet-latest",
                               max_tokens=2000, system=system,
                               messages=[{"role": "user", "content": user}])
        return m.content[0].text
    if provider == "openai" and settings.OPENAI_API_KEY:
        from openai import OpenAI
        cl = OpenAI(api_key=settings.OPENAI_API_KEY)
        r = cl.chat.completions.create(model=settings.LLM_MODEL or "gpt-4o-mini",
                                       messages=[{"role": "system", "content": system},
                                                 {"role": "user", "content": user}])
        return r.choices[0].message.content
    # offline fallback: return marker so callers use extractive path
    raise _OfflineSignal()


class _OfflineSignal(Exception):
    pass
