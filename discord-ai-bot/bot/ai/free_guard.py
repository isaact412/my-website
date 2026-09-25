"""The spending lock. Checked before EVERY AI call.

With ALLOW_PAID_MODELS=false (the default), a call only goes through if the
model is verifiably free. There is no code path that falls back to a paid model.
"""
import logging
import time

from bot.ai.providers.base import NotFreeError

log = logging.getLogger("bot.ai")

# Providers whose free tier is attached to the ACCOUNT, not the model.
# They can only charge you if you add a payment method to that account. Don't.
FREE_TIER_ACCOUNT_PROVIDERS = {"groq"}
LOCAL_PROVIDERS = {"ollama"}
OPENROUTER_FREE_ROUTER = "openrouter/free"
PRICE_RECHECK_SECONDS = 6 * 3600


class FreeGuard:
    def __init__(self, allow_paid: bool):
        self.allow_paid = allow_paid
        self._openrouter_free: set[str] = set()
        self._openrouter_checked_at: float | None = None  # None = never checked

    async def check(self, provider) -> None:
        """Raises NotFreeError if this call might cost money."""
        if self.allow_paid:
            return
        if provider.name in LOCAL_PROVIDERS or provider.name in FREE_TIER_ACCOUNT_PROVIDERS:
            return
        if provider.name == "openrouter":
            await self._check_openrouter(provider)
            return
        raise NotFreeError(f"{provider.name} is not a known free provider and ALLOW_PAID_MODELS=false")

    async def _check_openrouter(self, provider) -> None:
        model = provider.model
        if model == OPENROUTER_FREE_ROUTER:
            return  # OpenRouter's router that only ever picks free models
        if not model.endswith(":free"):
            raise NotFreeError(f"openrouter model {model!r} is not a ':free' model")

        # Free models sometimes become paid. Re-check OpenRouter's price list regularly.
        stale = self._openrouter_checked_at is None or time.monotonic() - self._openrouter_checked_at > PRICE_RECHECK_SECONDS
        if stale:
            models = await provider.list_models()
            self._openrouter_free = {
                m["id"] for m in models
                if _is_zero(m.get("pricing", {}).get("prompt")) and _is_zero(m.get("pricing", {}).get("completion"))
            }
            self._openrouter_checked_at = time.monotonic()
            log.info("openrouter: price list refreshed, %d free models", len(self._openrouter_free))
        if model not in self._openrouter_free:
            raise NotFreeError(f"openrouter model {model!r} is not listed at $0 right now")


def _is_zero(price) -> bool:
    try:
        return float(price) == 0.0
    except (TypeError, ValueError):
        return False
