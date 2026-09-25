"""Sends a request to the first free provider that's available, in AI_PROVIDER_CHAIN order."""
import logging
import time

import aiohttp

from bot.ai.free_guard import FreeGuard
from bot.ai.providers.base import (
    ChatMessage, ChatResult, NotFreeError, ProviderError, ProviderUnavailable, RateLimited,
)
from bot.ai.providers.openai_compatible import OpenAICompatibleProvider
from bot.config import Settings

log = logging.getLogger("bot.ai")


class AllProvidersUnavailable(Exception):
    """Every free provider is down, rate limited, or not free. Nothing was spent."""


class AIRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.guard = FreeGuard(settings.allow_paid_models)
        self._session: aiohttp.ClientSession | None = None
        self.providers: list[OpenAICompatibleProvider] = []
        self._cooling_until: dict[str, float] = {}

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40))
        self.providers = [OpenAICompatibleProvider(cfg, self._session) for cfg in self.settings.providers]
        mode = "PAID ALLOWED" if self.settings.allow_paid_models else "free only"
        log.info("AI providers: %s (%s)", ", ".join(p.name for p in self.providers) or "none", mode)
        for p in self.providers:
            try:
                await p.resolve_model()
                await self.guard.check(p)
                log.info("%s ready: model %s", p.name, p.model)
            except NotFreeError as e:
                log.error("%s disabled by the spending lock: %s", p.name, e)
            except ProviderError as e:
                log.warning("%s not ready yet (%s); will retry when needed", p.name, e)

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    async def chat(self, messages: list[ChatMessage], max_tokens: int = 300, temperature: float = 0.9) -> ChatResult:
        problems = []
        for p in self.providers:
            if time.monotonic() < self._cooling_until.get(p.name, 0):
                problems.append(f"{p.name}: cooling down")
                continue
            try:
                if p.model == "auto":
                    await p.resolve_model()
                await self.guard.check(p)  # the spending lock, every single call
                return await p.chat(messages, max_tokens, temperature)
            except NotFreeError as e:
                log.error("[AI] refused %s: %s", p.name, e)
                problems.append(f"{p.name}: not free")
            except RateLimited as e:
                self._cooling_until[p.name] = time.monotonic() + e.retry_after
                log.warning("[AI] %s rate limited; pausing it for %.0fs", p.name, e.retry_after)
                problems.append(f"{p.name}: rate limited")
            except ProviderUnavailable as e:
                self._cooling_until[p.name] = time.monotonic() + 60
                log.warning("[AI] %s unavailable: %s", p.name, e)
                problems.append(f"{p.name}: unavailable")
            except ProviderError as e:
                log.warning("[AI] %s error: %s", p.name, e)
                problems.append(f"{p.name}: error")
        log.warning("[AI] all free providers unavailable (%s)", "; ".join(problems) or "none configured")
        raise AllProvidersUnavailable("; ".join(problems))
