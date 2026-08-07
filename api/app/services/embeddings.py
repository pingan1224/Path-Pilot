"""Embedding client. The only file that knows which vendor produces vectors.

OpenAI rather than Moonshot because Moonshot has no embeddings endpoint (verified against
their API surface, not assumed). `dimensions=1024` matches the Vector(1024) column in
document_chunks — OpenAI's Matryoshka truncation makes the model fit our schema instead of
the schema chasing the model.
"""

from functools import lru_cache

from openai import OpenAI, OpenAIError

from app import faults
from app.config import settings
from app.models.knowledge import EMBEDDING_DIM


class EmbeddingsUnavailableError(RuntimeError):
    """Raised when embeddings cannot be produced — missing key or upstream failure.

    Callers are expected to degrade (keyword retrieval) rather than fail, and to say so:
    rule 6 requires the degraded mode to be visible, not silent.
    """


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    if not settings.openai_api_key:
        raise EmbeddingsUnavailableError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=settings.openai_api_key)


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts at the schema's dimensionality."""
    if not texts:
        return []
    # Injected at the vendor boundary rather than at the caller, so a fault run exercises
    # the same except path a real outage would.
    if faults.is_armed("embeddings.unavailable"):
        raise EmbeddingsUnavailableError("injected fault: embeddings.unavailable")
    try:
        response = get_client().embeddings.create(
            model=settings.embedding_model,
            input=texts,
            dimensions=EMBEDDING_DIM,
        )
    except OpenAIError as exc:
        raise EmbeddingsUnavailableError(f"Embedding call failed: {exc}") from exc

    # The API returns items with an index field; sort defensively rather than assuming
    # order, because a silent mis-alignment here would poison every retrieval after it.
    items = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in items]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
