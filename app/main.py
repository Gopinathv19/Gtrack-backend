"""FastAPI application entry-point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy.exc import IntegrityError

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.base_class import Base
from app.db.session import engine

logger = logging.getLogger("gtrack")
logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG)


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks.

    In development we *try* to auto-create tables, but we never crash the
    app if the database is unreachable — that way `/docs` still works and
    you can see what's wrong from the logs.
    """
    import app.models  # noqa: F401  ensure models are registered on Base.metadata
    if settings.APP_ENV == "development":
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Tables ensured (dev auto-create).")
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Skipping auto-create — could not reach DB at startup: %s", exc
            )
    yield



app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Error handlers
@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    logger.warning("IntegrityError: %s", exc)
    return JSONResponse(
        status_code=409,
        content={"detail": "Resource conflict (duplicate or constraint violation)"},
    )


@app.get("/", tags=["health"])
def root():
    return {"app": settings.APP_NAME, "version": "1.0.0", "status": "ok"}


@app.get("/health", tags=["health"])
def health():
    return {"status": "healthy"}


app.include_router(api_router, prefix=settings.API_V1_PREFIX)
