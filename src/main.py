import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.v1.router import api_router
from src.core.config import Config
from src.core.csrf import CSRFMiddleware
from src.core.exceptions import register_exception_handlers
from src.core.logging import RequestContextMiddleware, configure_logging
from src.db.mains import async_engine

version = "v1"

configure_logging("WARNING" if Config.APP_ENV == "test" else "INFO")

app = FastAPI(
    title="CDS Attend API",
    summary="NYSC Community Development Service attendance management.",
    version=version,
    # Interactive docs are useful in dev/staging; hide them in production.
    docs_url=None if Config.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if Config.is_production else "/openapi.json",
)

register_exception_handlers(app)

# Starlette runs the last-added middleware first: CORS -> request context -> CSRF -> app.
app.add_middleware(CSRFMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Authorization"],
    expose_headers=["X-Request-ID"],
)


@app.get("/", include_in_schema=False)
async def welcome():
    return {"message": "Welcome to the CDS Attend API."}


@app.get("/health", tags=["Health"])
async def health():
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/ready", tags=["Health"])
async def ready():
    """Readiness: the database is reachable. Deliberately reveals no dependency details."""
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logging.getLogger("cds.health").exception("readiness_check_failed")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}


app.include_router(api_router)
