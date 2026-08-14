"""Chat-model client. The only file that knows which vendor serves the conversation.

OpenAI since 2026-08-14; Moonshot Kimi before that, over the same SDK — which is why the
swap was this file, two settings, and nothing else.

Constraints of the gpt-5 reasoning family, checked by running scripts/verify_keys.py
rather than assumed — and notably the same shape as Kimi's, so nothing downstream moved:
- Only the default temperature is accepted, so we never send the parameter. Determinism
  for evaluation has to come from eval design, not temperature=0.
- Thinking consumes output tokens, so the completion budget must be generous or the
  visible answer arrives empty. `max_tokens` is rejected outright for these models;
  `max_completion_tokens` is the parameter, and the non-reasoning lines accept it too.
"""

from functools import lru_cache
from typing import Any

from openai import OpenAI

from app import faults
from app.config import settings


class LlmNotConfiguredError(RuntimeError):
    """Raised when the assistant is asked to run without a chat-model key set."""


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    if not settings.openai_api_key:
        raise LlmNotConfiguredError(
            "OPENAI_API_KEY is not set. The assistant is unavailable; "
            "the rest of the API is unaffected."
        )
    return OpenAI(api_key=settings.openai_api_key)


def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    max_tokens: int = 4096,
) -> Any:
    """One completion turn. Returns the raw message (content and/or tool_calls)."""
    # Stands in for an upstream 4xx/5xx or a timeout. The agent loop catches every
    # exception from this call, so the shape of the failure does not matter — only that
    # the turn ends as a routed escalation with a case number instead of a bare 500.
    faults.fail_if_armed("llm.error")

    kwargs: dict[str, Any] = {
        "model": settings.chat_model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }
    if settings.chat_reasoning_effort is not None:
        kwargs["reasoning_effort"] = settings.chat_reasoning_effort
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
