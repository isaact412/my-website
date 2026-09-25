"""What every AI provider looks like to the rest of the bot."""
from dataclasses import dataclass


@dataclass
class ChatMessage:
    role: str      # "system" | "user" | "assistant"
    content: str


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(Exception):
    """The provider failed in a way worth logging, e.g. a bad response."""


class RateLimited(ProviderError):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after:.0f}s")
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """Down, unreachable, or no usable model right now."""


class NotFreeError(ProviderError):
    """The configured model isn't verifiably free, and paid models are not allowed."""
