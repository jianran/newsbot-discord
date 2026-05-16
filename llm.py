"""LLM client for news summarization and analysis."""

import os
import json
from typing import Optional
import httpx


class LLMClient:
    """Unified client for OpenAI and Anthropic APIs."""

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")

        if not self.api_key:
            print("⚠️  LLM_API_KEY not set — summarization will be disabled")
            self.enabled = False
        else:
            self.enabled = True

    def _build_headers(self) -> dict:
        if self.provider == "anthropic":
            return {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        return {
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }

    def _build_payload(self, system: str, messages: list, max_tokens: int = 500):
        if self.provider == "anthropic":
            return {
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": messages,
            }
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *messages],
        }

    def _get_api_url(self) -> str:
        if self.provider == "anthropic":
            return "https://api.anthropic.com/v1/messages"
        return "https://api.openai.com/v1/chat/completions"

    def _extract_text(self, response: dict) -> str:
        if self.provider == "anthropic":
            return response.get("content", [{}])[0].get("text", "")
        return response.get("choices", [{}])[0].get("message", {}).get("content", "")

    async def summarize(self, title: str, text: str, source: str) -> Optional[str]:
        """Summarize a news article in 2-3 sentences."""
        if not self.enabled:
            return None

        system = "You are a news editor. Summarize articles concisely in 2-3 sentences. Be neutral and factual. Output only the summary, no preamble."
        user = f"Source: {source}\nTitle: {title}\n\nArticle:\n{text[:3000]}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._get_api_url(),
                    headers=self._build_headers(),
                    json=self._build_payload(system, [{"role": "user", "content": user}]),
                )
                resp.raise_for_status()
                return self._extract_text(resp.json())
        except Exception as e:
            print(f"LLM summarization error: {e}")
            return None

    async def detect_tension(self, articles: list) -> Optional[str]:
        """Detect contradictions or tensions between multiple articles on the same story."""
        if not self.enabled or len(articles) < 2:
            return None

        system = "You are a media analyst. Compare these articles from different sources. Identify: 1) What they agree on 2) Where they contradict each other 3) Key framing differences in framing. Be specific and cite sources. Output 3-5 bullet points."
        user = ""
        for i, a in enumerate(articles, 1):
            user += f"\n--- Article {i}: {a['source']} — {a['title']} ---\n{a.get('summary', a['title'][:500])}\n"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._get_api_url(),
                    headers=self._build_headers(),
                    json=self._build_payload(system, [{"role": "user", "content": user}]),
                )
                resp.raise_for_status()
                return self._extract_text(resp.json())
        except Exception as e:
            print(f"Tension detection error: {e}")
            return None

    async def why_it_matters(self, title: str, text: str) -> Optional[str]:
        """Generate 'why this matters' context."""
        if not self.enabled:
            return None

        system = "You are a geopolitical analyst. Explain why this news story matters — context, implications, what to watch next. Keep it to 2-3 sentences."
        user = f"Title: {title}\n\nArticle:\n{text[:2000]}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._get_api_url(),
                    headers=self._build_headers(),
                    json=self._build_payload(system, [{"role": "user", "content": user}]),
                )
                resp.raise_for_status()
                return self._extract_text(resp.json())
        except Exception as e:
            print(f"Context error: {e}")
            return None

    async def track_evolution(self, story_history: list) -> Optional[str]:
        """Track how a story evolved over time."""
        if not self.enabled or len(story_history) < 2:
            return None

        system = "You are a news timeline analyst. Show how this story evolved — key developments, turning points, narrative shifts. Keep it concise."
        user = json.dumps(story_history[-10:], indent=2)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._get_api_url(),
                    headers=self._build_headers(),
                    json=self._build_payload(system, [{"role": "user", "content": user}]),
                )
                resp.raise_for_status()
                return self._extract_text(resp.json())
        except Exception as e:
            print(f"Evolution error: {e}")
            return None
