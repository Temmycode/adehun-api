import json
import logging
from contextlib import asynccontextmanager

import cloudinary
import firebase_admin
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import credentials
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.logging import configure_logging, silence_third_party_loggers
from app.rate_limiting import limiter

from .routers import agreement, asset, auth, condition, dev, stats, user

if settings.debug:
    from .routers import dev

logger = logging.getLogger(__name__)


# INFO: Logging setup
configure_logging()
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

if settings.debug:
    app.include_router(dev.router)


@app.get("/")
def root():
    return {"message": "Hello, World!"}
