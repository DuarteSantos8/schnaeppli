from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import ai, auth, budget, deals, images, me, misc, searches, shops, wishlist
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import setup_logging
from app.core.security import client_ip, ip_allowed

log = structlog.get_logger()
MAX_BODY = 256 * 1024


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()
    app = FastAPI(
        title="Schnäppli",
        version="0.1.0",
        docs_url="/api/docs" if settings.env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.env != "production" else None,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=rid)
        ip = client_ip(request)
        if not ip_allowed(ip) and request.url.path not in ("/api/health",):
            log.warning("blocked_network", ip=ip, path=request.url.path)
            return JSONResponse({"detail": "Not available from this network."}, status_code=403)
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY:
            return JSONResponse({"detail": "Request too large."}, status_code=413)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            # Cross-site requests are rejected outright (in addition to SameSite + CSRF token).
            origin = request.headers.get("origin")
            if (
                origin
                and origin.rstrip("/") != settings.public_url.rstrip("/")
                and settings.env == "production"
            ):
                return JSONResponse({"detail": "Cross-origin request rejected."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        structlog.contextvars.clear_contextvars()
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg")}
            for e in exc.errors()
        ]
        return JSONResponse({"detail": "Some fields are invalid.", "errors": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception):
        log.exception("unhandled_error", error_type=type(exc).__name__)
        return JSONResponse({"detail": "Something went wrong on our side."}, status_code=500)

    @app.get("/api/health")
    async def health():
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    for r in (
        auth.router,
        me.router,
        searches.router,
        deals.router,
        wishlist.router,
        budget.router,
        ai.router,
        misc.router,
        images.router,
        shops.router,
    ):
        app.include_router(r)
    return app


app = create_app()
