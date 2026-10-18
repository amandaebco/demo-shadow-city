"""Gemma backend for System One (Layer 5): Ollama on a private Cloud Run GPU service.

Same prompt and JSON schema as the Gemini decider; Ollama constrains the output to the schema.
Calls carry a Google-signed ID token for the service URL (Cloud Run invoker).
"""

import asyncio
import json
import time

import httpx

from app.costs import Usage

TOKEN_TTL_S = 45 * 60


class IdTokenProvider:
    """Caches an ID token for one audience; fetched from the metadata server on Cloud Run."""

    def __init__(self, audience: str):
        self._audience = audience
        self._token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        async with self._lock:
            if not self._token or time.monotonic() >= self._expires:
                self._token = await asyncio.to_thread(self._fetch)
                self._expires = time.monotonic() + TOKEN_TTL_S
            return self._token

    def _fetch(self) -> str:
        import google.auth.transport.requests
        import google.oauth2.id_token

        return google.oauth2.id_token.fetch_id_token(google.auth.transport.requests.Request(), self._audience)


class OllamaGemma:
    def __init__(self, base_url: str, model: str, tokens=None, timeout_s: float = 120.0, transport=None,
                 think: bool = False):
        self.model = model
        # System One must be fast: Gemma 4's thinking mode is off unless asked for.
        self._think = think
        self._transport = transport
        self._url = base_url.rstrip("/") + "/api/chat"
        self._tokens = tokens
        self._timeout = timeout_s

    async def ask(self, system: str, prompt: str, schema: dict) -> tuple[dict, Usage | None]:
        headers = {"Authorization": f"Bearer {await self._tokens.get()}"} if self._tokens else {}
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            "think": self._think,
            "options": {"temperature": 0},
        }
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.post(self._url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
        parsed = json.loads(data["message"]["content"])
        if not isinstance(parsed, dict):
            raise ValueError("Gemma returned non-object JSON")
        # GPU time, not tokens, is what Gemma costs; leave cost_usd unpriced.
        usage = Usage(self.model, data.get("prompt_eval_count", 0), data.get("eval_count", 0), 0, None)
        return parsed, usage
