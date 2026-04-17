import json
from contextlib import asynccontextmanager

import cloudinary
from fastapi.exceptions import RequestValidationError
import firebase_admin
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import credentials
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.core.response import error_response
from app.exceptions import AppError
from app.logging import get_logger, silence_third_party_loggers
from app.rate_limiting import limiter

from .routers import agreement, asset, auth, condition, dev, notification, stats, user

if settings.debug:
    from .routers import dev

logger = get_logger(__name__)


# INFO: Logging setup
silence_third_party_loggers()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    yield
    logger.info("Application shutdown...")


cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_secret_key,
    secure=True,
)
origins = ["*"]

# Firebase Admin SDK initialization
with open("./secrets/firebase.json") as account_file:
    service_account = json.load(account_file)

cred = credentials.Certificate(service_account)
firebase_admin.initialize_app(cred)

app = FastAPI(title="Adehun API", version="1.0.0", lifespan=lifespan)
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
async def value_error_exception_handler(request: Request, exc: AppError):
    return error_response(
        code=exc.code, message=exc.message, status_code=exc.status_code
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception",
        exc_info=True,
        extra={"meta": {"path": request.url.path, "error": str(exc)}},
    )
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred. Please try again later.",
        status_code=500,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth.router)
app.include_router(user.router)
app.include_router(agreement.router)
app.include_router(condition.router)
app.include_router(asset.router)
app.include_router(stats.router)
app.include_router(notification.router)

if settings.debug:
    app.include_router(dev.router)


@app.get("/")
def root():
    return {"message": "Hello, World!"}
