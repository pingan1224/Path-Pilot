"""UAX API entrypoint.

Run locally:
    .venv\\Scripts\\uvicorn app.main:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db.session import DatabaseNotConfiguredError
from app.routers import advisors, assistant, auth, cases, health, registrar, students

app = FastAPI(
    title="UAX API",
    description="Unified Academic Experience — AI-enhanced student information system.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Identity lives in a signed cookie. `same_site="lax"` plus an explicit origin allowlist
# in CORS is what keeps another site from riding the session; `https_only` follows the
# deployment so local development over http still works.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="uax_session",
    same_site="lax",
    https_only=settings.session_https_only,
    max_age=60 * 60 * 8,
)

STATUS_CODES = {
    400: "bad_request",
    404: "not_found",
    409: "conflict",
    422: "invalid_request",
    500: "internal_error",
    503: "service_unavailable",
}


def _error(status_code: int, message: str, code: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code or STATUS_CODES.get(status_code, "error"),
                "message": message,
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _error(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", ())[1:]) or "request"
    return _error(422, f"{field}: {first.get('msg', 'is invalid')}")


@app.exception_handler(DatabaseNotConfiguredError)
async def database_not_configured_handler(
    _: Request, exc: DatabaseNotConfiguredError
) -> JSONResponse:
    # Rule 6: name the missing dependency rather than returning a bare 500. A caller that
    # gets this back knows the service is up and what specifically is unavailable.
    return _error(503, str(exc), code="database_not_configured")


app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(students.router, prefix="/api/v1")
app.include_router(advisors.router, prefix="/api/v1")
app.include_router(registrar.router, prefix="/api/v1")
app.include_router(cases.router, prefix="/api/v1")
app.include_router(assistant.router, prefix="/api/v1")
