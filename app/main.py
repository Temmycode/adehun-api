import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.logging import configure_logging, silence_third_party_loggers
from app.rate_limiting import limiter

logger = logging.getLogger(__name__)


# INFO: Logging setup
configure_logging()
silence_third_party_loggers()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    yield
    logger.info("Application shutdown...")


app = FastAPI(title="Adehun API", version="1.0.0", lifespan=lifespan)


@app.get("/")
@limiter.limit("100/minute")
def root():
    return {"message": "Hello, World!"}
