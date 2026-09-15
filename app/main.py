import json
from contextlib import asynccontextmanager

import cloudinary
import firebase_admin
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import credentials
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.core.response import error_response
from app.exceptions import AppError
from app.logging import get_logger, silence_third_party_loggers
from app.rate_limiting import limiter
from app.routers import (
    admin_dispute,
    agreement,
    asset,
    auth,
    bank_account,
    condition,
    dispute,
    invitation,
    notification,
    stats,
    transaction,
    user,
    wallet,
)
from app.service.paystack_client import paystack_client

logger = get_logger(__name__)

silence_third_party_loggers()


def init_integrations() -> None:
    """Configure third-party SDKs. Idempotent, and never fatal on failure."""
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            send_default_pii=False,
            traces_sample_rate=0.1,
        )

    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_secret_key,
        secure=True,
    )

    raw_service_account = settings.firebase_service_account_json.strip()
    if not firebase_admin._apps and raw_service_account not in {"", "{}"}:
        try:
            cert = credentials.Certificate(json.loads(raw_service_account))
            firebase_admin.initialize_app(cert)
            logger.info("Firebase Admin initialized")
        except Exception:
            logger.exception("Firebase Admin init failed — Firebase auth disabled")
    elif not firebase_admin._apps:
        logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON unset — Firebase auth disabled")


init_integrations()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting application", extra={"environment": settings.environment}
    )
    yield
    await paystack_client.aclose()
    logger.info("Application shutdown")


# Interactive docs are a debug-only convenience. They enumerate every route
# and, in older builds, wired the Authorize button to the dev login bypass.
_docs_enabled = settings.debug and not settings.is_production

app = FastAPI(
    title="Adehun API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,  # pyright: ignore[reportArgumentType]
)
app.add_middleware(SlowAPIMiddleware)

_HTTP_STATUS_TO_ERROR_CODE = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    410: "GONE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_SERVER_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code = _HTTP_STATUS_TO_ERROR_CODE.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return error_response(code=code, message=message, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    msg = first.get("msg", "Invalid request payload")
    message = f"{loc}: {msg}" if loc else msg
    return error_response(code="VALIDATION_ERROR", message=message, status_code=422)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return error_response(
        code=exc.code, message=exc.message, status_code=exc.status_code
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # The traceback is attached by logger.exception; never stringify the
    # exception into the log record — driver errors embed connection URLs.
    logger.exception(
        "Unhandled exception",
        extra={"meta": {"path": request.url.path, "type": type(exc).__name__}},
    )
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred. Please try again later.",
        status_code=500,
    )


# A wildcard origin combined with allow_credentials is an any-site CSRF grant.
# Browser origins are opt-in via CORS_ORIGINS; the mobile app needs none.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )


app.include_router(auth.router)
app.include_router(user.router)
app.include_router(wallet.router)
app.include_router(agreement.router)
app.include_router(condition.router)
app.include_router(asset.router)
app.include_router(stats.router)
app.include_router(notification.router)
app.include_router(transaction.router)
app.include_router(bank_account.router)
app.include_router(dispute.router)
app.include_router(admin_dispute.router)
app.include_router(invitation.router)

if settings.debug and not settings.is_production:
    # Imported lazily so the module (and its bypass routes) never load in prod.
    from app.routers import dev

    app.include_router(dev.router)
    logger.warning("dev router enabled — DEBUG=true")


@app.get("/", include_in_schema=False)
def root():
    return {"status": "ok", "service": "adehun-api"}


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
