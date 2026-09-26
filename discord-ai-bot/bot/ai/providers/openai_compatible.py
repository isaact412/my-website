"""One client for every provider that speaks the OpenAI-style chat API (Groq, OpenRouter, Ollama)."""
import logging
import re

import aiohttp

from bot.ai.providers.base import (
    ChatMessage, ChatResult, ProviderError, ProviderUnavailable, RateLimited,
)
from bot.config import ProviderConfig

log = logging.getLogger("bot.ai")

# When GROQ_MODEL=auto, the first of these that Groq currently offers is used.
# Chat-tuned models first; reasoning models after.
GROQ_PREFERENCE = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]
_NOT_CHAT = re.compile(r"whisper|guard|tts|embed|orpheus|playai|compound|prompt", re.I)
_THINK_TAGS = re.compile(r"<think>.*?</think>", re.S | re.I)


class OpenAICompatibleProvider:
    def __init__(self, cfg: ProviderConfig, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.name = cfg.name
        self.model = cfg.model
        self._session = session

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}

    async def list_models(self) -> list[dict]:
        """Raw model list from the provider (includes pricing on OpenRouter)."""
        try:
            async with self._session.get(f"{self.cfg.base_url}/models", headers=self._headers()) as r:
                if r.status in (401, 403):
                    raise ProviderUnavailable(f"{self.name} rejected the API key (HTTP {r.status})")
                if r.status >= 400:
                    raise ProviderUnavailable(f"{self.name} /models returned HTTP {r.status}")
                data = await r.json()
        except aiohttp.ClientError as e:
            raise ProviderUnavailable(f"{self.name} unreachable: {e.__class__.__name__}") from e
        return data.get("data", []) if isinstance(data, dict) else []

    async def resolve_model(self) -> str:
        """Turns MODEL=auto into a real model ID that exists right now (for Ollama: one you've downloaded)."""
        if self.cfg.model != "auto":
            return self.model
        available = [m.get("id", "") for m in await self.list_models()]
        if self.name == "ollama":
            # Skip ":cloud" models: those run on Ollama's servers, not your Mac.
            chat = [m for m in available if m and not _NOT_CHAT.search(m) and not is_ollama_cloud(m)]
            if not chat:
                raise ProviderUnavailable("ollama has no models downloaded yet (run: ollama pull <model>)")
            self.model = chat[0]
            log.info("ollama: using downloaded model %s", self.model)
            return self.model
        for wanted in GROQ_PREFERENCE:
            if wanted in available:
                self.model = wanted
                break
        else:
            chat_models = sorted(m for m in available if m and not _NOT_CHAT.search(m))
            if not chat_models:
                raise ProviderUnavailable(f"{self.name} lists no usable chat models")
            self.model = chat_models[0]
        log.info("%s: auto-picked model %s", self.name, self.model)
        return self.model

    async def chat(self, messages: list[ChatMessage], max_tokens: int, temperature: float) -> ChatResult:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if "gpt-oss" in self.model:
            # Reasoning model: keep its hidden thinking short so replies are fast and cheap on quota.
            payload["reasoning_effort"] = "low"
        try:
            async with self._session.post(
                f"{self.cfg.base_url}/chat/completions", json=payload, headers=self._headers()
            ) as r:
                if r.status == 429:
                    raise RateLimited(_retry_after(r.headers))
                if r.status in (401, 403):
                    raise ProviderUnavailable(f"{self.name} rejected the API key (HTTP {r.status})")
                if r.status == 402:
                    # "Payment required": this call would cost money. Never retry it.
                    raise ProviderUnavailable(f"{self.name} says this model requires payment (HTTP 402)")
                if r.status >= 500:
                    raise ProviderUnavailable(f"{self.name} server error (HTTP {r.status})")
                if r.status >= 400:
                    body = (await r.text())[:300]
                    raise ProviderError(f"{self.name} HTTP {r.status}: {body}")
                data = await r.json(content_type=None)
        except aiohttp.ClientError as e:
            raise ProviderUnavailable(f"{self.name} unreachable: {e.__class__.__name__}") from e
        except TimeoutError as e:
            raise ProviderUnavailable(f"{self.name} timed out") from e

        try:
            text = data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(f"{self.name} returned an unexpected response shape") from e

        usage = data.get("usage") or {}
        return ChatResult(
            text=_THINK_TAGS.sub("", text).strip(),
            provider=self.name,
            model=data.get("model", self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )


def is_ollama_cloud(model: str) -> bool:
    return model.endswith(":cloud") or model.endswith("-cloud")


def _retry_after(headers) -> float:
    for key in ("retry-after", "x-ratelimit-reset-requests"):
        raw = headers.get(key)
        if raw:
            try:
                return max(1.0, float(raw.rstrip("s")))
            except ValueError:
                pass
    return 30.0
