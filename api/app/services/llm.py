"""Chat-model client. The only file that knows which vendor serves the conversation.

Moonshot's endpoint is OpenAI-compatible, so the OpenAI SDK does the transport and this
module only pins down our usage of it. Swapping vendors means editing this file and
nothing else.

Two Kimi-specific constraints, both discovered by running scripts/verify_keys.py rather
than assumed:
- kimi-k3 rejects any temperature except 1, so we never send the parameter. Determinism
  for evaluation has to come from eval design, not temperature=0.
- It is a reasoning model: thinking consumes output tokens, so max_tokens must be generous
  or the visible answer arrives empty.
"""

from functools import lru_cache
from typing import Any

from openai import OpenAI

from app.config import settings


class LlmNotConfiguredError(RuntimeError):
    """Raised when the assistant is asked to run without a chat-model key set."""


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    if not settings.moonshot_api_key:
        raise LlmNotConfiguredError(
            "MOONSHOT_API_KEY is not set. The assistant is unavailable; "
            "the rest of the API is unaffected."
        )
    return OpenAI(api_key=settings.moonshot_api_key, base_url=settings.moonshot_base_url)


def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    max_tokens: int = 4096,
) -> Any:
    """One completion turn. Returns the raw message (content and/or tool_calls)."""
    kwargs: dict[str, Any] = {
        "model": settings.chat_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice

    response = get_client().chat.completions.create(**kwargs)
    choice = response.choices[0]
    usage = response.usage
    return choice.message, {
        "input_tokens": usage.prompt_tokens if usage else None,
        "output_tokens": usage.completion_tokens if usage else None,
    }
