import logging
from contextlib import asynccontextmanager

import cloudinary
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database import create_db_and_tables
from app.logging import configure_logging, silence_third_party_loggers
from app.rate_limiting import limiter

logger = logging.getLogger(__name__)


# INFO: Logging setup
configure_logging()
silence_third_party_loggers()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    create_db_and_tables()
    yield
    logger.info("Application shutdown...")


cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_secret_key,
    secure=True,
)
origins = ["*"]

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


@app.get("/")
def root():
    return {"message": "Hello, World!"}
