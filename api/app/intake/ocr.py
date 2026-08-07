"""Reading a transcript that arrived as a photo or a scan.

**Everything this module produces is untrusted by construction.** A text-layer PDF states
its characters; an image only suggests them, and the characters a transcript is made of are
exactly the ones that degrade into each other — `B`/`8`, `0`/`O`, `1`/`l`, `A-`/`A`. A
misread grade is the failure this whole feature is gated against, because it enters a degree
audit looking identical to a correct one and nothing downstream will ever catch it.

So the rule is structural, not procedural: `app.intake.service` forces every row that came
through this path to `needs_review`, whatever the parser thought of it. There is no
confidence threshold that promotes an OCR row to `matched`, because a confidence score from
a model that cannot see the original document is a claim about its own certainty, not about
the transcript.

**The image leaves this machine.** It is sent to OpenAI's vision endpoint, and that is a
different promise from the one the rest of intake makes ("the uploaded bytes are never
persisted" is about *this* system). The student is told before they upload, in the endpoint's
own disclosure and in the UI — a transcript is not something to send to a third party on
someone's behalf without saying so. Chosen over a local tesseract install deliberately:
tesseract needs a system binary everywhere this deploys and is markedly worse on phone
photos, which is the case that motivated the feature at all.

The prompt asks for transcription, never interpretation. A model asked to "read this
transcript" will helpfully repair a course code into one that exists, normalise a term, or
drop a row it thinks is a header — each of which produces a plausible record of a document
nobody has. It is asked for lines, in order, as they appear.
"""

import base64

from app import faults
from app.config import settings

# Vision-capable and cheap enough to run on every upload. Pinned rather than floating: an
# OCR accuracy number is meaningless if the thing being measured changes underneath it.
OCR_MODEL = "gpt-4o-mini"

# A transcript page is dense but small. Enough for a two-page record read line by line.
MAX_OCR_TOKENS = 4096

# Images larger than this are downscaled before sending — a 12MP phone photo costs tokens
# proportional to its size and adds no legible detail beyond roughly this width.
MAX_IMAGE_WIDTH = 1600

TRANSCRIPT_PROMPT = """Transcribe this academic transcript image to plain text.

Rules:
- Output the visible lines in reading order, one per line. Nothing else — no commentary,
  no summary, no markdown.
- Transcribe EXACTLY what is printed. Do not correct, complete, or normalise anything.
- If a course code looks unusual, transcribe the characters you see. Do not change it into
  a code you think is more likely.
- If a character is genuinely illegible, write ? in its place rather than guessing.
- Do not omit lines that look like headers, totals, or GPA summaries. Include them.
- Do not add a course, a grade, a term, or a credit value that is not printed on the page."""


class OcrUnavailableError(RuntimeError):
    """Raised when an image cannot be read — no key, upstream failure, or injected fault.

    Callers degrade to the honest refusal that existed before OCR (rule 6): say the file is
    a photo and point at the text-PDF export. A failure here must never become an empty
    reading, which would read as "your transcript has no courses".
    """


def _client():
    from openai import OpenAI

    if not settings.openai_api_key:
        raise OcrUnavailableError("OPENAI_API_KEY is not set, so images cannot be read.")
    return OpenAI(api_key=settings.openai_api_key)


def downscale(data: bytes) -> bytes:
    """Shrink an oversized photo. Returns the original bytes if it is already small."""
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        if image.width <= MAX_IMAGE_WIDTH:
            return data
        ratio = MAX_IMAGE_WIDTH / image.width
        resized = image.convert("RGB").resize(
            (MAX_IMAGE_WIDTH, int(image.height * ratio)), Image.LANCZOS
        )
        buffer = io.BytesIO()
        resized.save(buffer, format="JPEG", quality=88)
        return buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError):
        # Not decodable as an image here; let the vision endpoint be the judge.
        return data


def read_image(data: bytes, *, mime: str = "image/jpeg") -> str:
    """Transcribe one page image to text. Raises OcrUnavailableError on any failure."""
    # Raised as the domain error, not as InjectedFault. An injection point that throws an
    # exception type the caller does not catch is testing a failure that cannot happen —
    # it escaped `_read_photo` and crashed the request the first time it ran, which is a
    # bug in the probe rather than in the product, and exactly as misleading.
    if faults.is_armed("ocr.unavailable"):
        raise OcrUnavailableError("injected fault: ocr.unavailable")

    payload = downscale(data)
    encoded = base64.b64encode(payload).decode("ascii")
    try:
        response = _client().chat.completions.create(
            model=OCR_MODEL,
            max_tokens=MAX_OCR_TOKENS,
            # Transcription, not generation. The lowest temperature the endpoint allows,
            # because every degree of freedom here is a degree of freedom to invent a grade.
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": TRANSCRIPT_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                    ],
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001 — every upstream failure degrades identically
        raise OcrUnavailableError(f"The image could not be read: {type(exc).__name__}") from exc

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise OcrUnavailableError("The image was read but produced no text.")
    return text
