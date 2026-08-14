"""Confirm the provider key actually works before anything depends on it.

    .venv/Scripts/python -m scripts.verify_keys

One vendor since 2026-08-14 (chat, tool calling and embeddings all on OPENAI_API_KEY),
so one check function with three probes: chat, tool calling (the agent loop depends on
it), and an embedding at our 1024 dimensions. Each prints enough to eyeball; a failure
names the probe at fault.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

EMBEDDING_DIM = 1024


def check_openai() -> None:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    models = [m.id for m in client.models.list().data]
    print(f"[openai] models visible : {len(models)}")
    chat_model = os.environ.get("CHAT_MODEL", "gpt-5.4-mini")
    marker = "yes" if chat_model in models else "NOT FOUND — pick from the account's list"
    print(f"[openai] {chat_model!r} available: {marker}")

    # The gpt-5 reasoning family rejects any temperature but the default, so we never
    # send the parameter — determinism has to come from evaluation design. It also
    # rejects max_tokens; max_completion_tokens is the one that works, and reasoning
    # spends from it, so a tight budget yields an empty visible answer.
    response = client.chat.completions.create(
        model=chat_model,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
        max_completion_tokens=512,
    )
    print(f"[openai] chat           : {response.choices[0].message.content!r}")

    # Tool calling is the capability the whole agent loop rests on; verify it, not hope.
    tool_response = client.chat.completions.create(
        model=chat_model,
        messages=[{"role": "user", "content": "What courses does the plan for student 7 hold?"}],
        max_completion_tokens=512,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_my_plan",
                    "description": "List the courses on a student's self-reported plan",
                    "parameters": {
                        "type": "object",
                        "properties": {"student_id": {"type": "integer"}},
                        "required": ["student_id"],
                    },
                },
            }
        ],
    )
    calls = tool_response.choices[0].message.tool_calls
    if calls:
        print(f"[openai] tool call      : {calls[0].function.name}({calls[0].function.arguments})")
    else:
        print("[openai] tool call      : MODEL DID NOT CALL THE TOOL")

    embedding = client.embeddings.create(
        model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        input=["registration hold financial aid"],
        dimensions=EMBEDDING_DIM,
    )
    vector = embedding.data[0].embedding
    print(f"[openai] embedding dims : {len(vector)} (expected {EMBEDDING_DIM})")
    print(f"[openai] tokens billed  : {embedding.usage.total_tokens}")


def main() -> None:
    try:
        check_openai()
    except Exception as exc:  # noqa: BLE001 — report with the probe visible above
        print(f"[openai] FAILED: {type(exc).__name__}: {exc}")
        print()
        print("FAILED: openai")
        return

    print()
    print("all keys verified")


if __name__ == "__main__":
    main()
