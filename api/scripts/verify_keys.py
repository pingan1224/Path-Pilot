"""Confirm both provider keys actually work before any P3 code depends on them.

    .venv/Scripts/python -m scripts.verify_keys

Three checks: Moonshot chat, Moonshot tool calling (the agent loop depends on it), and an
OpenAI embedding at our 1024 dimensions. Each prints enough to eyeball; any failure names
the key at fault.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

EMBEDDING_DIM = 1024


def check_moonshot() -> None:
    client = OpenAI(
        api_key=os.environ["MOONSHOT_API_KEY"],
        base_url=os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
    )

    models = [m.id for m in client.models.list().data]
    print(f"[moonshot] models visible : {len(models)}")
    chat_model = os.environ.get("CHAT_MODEL", "kimi-k3")
    marker = "yes" if chat_model in models else "NOT FOUND — pick from list above"
    print(f"[moonshot] {chat_model!r} available: {marker}")
    if chat_model not in models:
        for m in sorted(models):
            print(f"           - {m}")

    # kimi-k3 is a reasoning model and rejects any temperature other than 1, so we simply
    # never send the parameter. Worth remembering for the agent: determinism has to come
    # from evaluation design, not from temperature=0.
    response = client.chat.completions.create(
        model=chat_model,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
        max_tokens=64,
    )
    print(f"[moonshot] chat            : {response.choices[0].message.content!r}")

    # Tool calling is the capability the whole agent loop rests on; verify it, not hope.
    tool_response = client.chat.completions.create(
        model=chat_model,
        messages=[{"role": "user", "content": "What holds does student 7 have?"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_active_holds",
                    "description": "List active holds on a student's record",
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
        print(f"[moonshot] tool call       : {calls[0].function.name}({calls[0].function.arguments})")
    else:
        print("[moonshot] tool call       : MODEL DID NOT CALL THE TOOL")


def check_openai() -> None:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.embeddings.create(
        model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        input=["registration hold financial aid"],
        dimensions=EMBEDDING_DIM,
    )
    vector = response.data[0].embedding
    print(f"[openai]   embedding dims  : {len(vector)} (expected {EMBEDDING_DIM})")
    print(f"[openai]   tokens billed   : {response.usage.total_tokens}")


def main() -> None:
    failures = []
    for name, check in (("moonshot", check_moonshot), ("openai", check_openai)):
        try:
            check()
        except Exception as exc:  # noqa: BLE001 — report, don't crash the other check
            failures.append(name)
            print(f"[{name}] FAILED: {type(exc).__name__}: {exc}")

    print()
    print("all keys verified" if not failures else f"FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
