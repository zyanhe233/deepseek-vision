"""FastAPI application."""
import logging
import os
import re
import tracemalloc
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.config import settings
from app.messages import router as messages_router
from app.models import router as models_router

_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class _AnsiStrippingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _ANSI_ESCAPE.sub("", super().format(record))


_console = logging.StreamHandler()
_console.setFormatter(_formatter)

os.makedirs("logs", exist_ok=True)
from logging.handlers import TimedRotatingFileHandler
_file_handler = TimedRotatingFileHandler(
    "logs/app.log", when="midnight", interval=1, backupCount=1, encoding="utf-8"
)
_file_handler.setFormatter(
    _AnsiStrippingFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

logging.basicConfig(level=_log_level, handlers=[_console, _file_handler])


class _Drop404Filter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return " 404 " not in msg


logging.getLogger("uvicorn.access").addFilter(_Drop404Filter())

_scan_logger = logging.getLogger("app.scan")

ALLOWED_ROUTES: set[tuple[str, str]] = {
    ("GET", "/health"),
    ("GET", "/v1/models"),
    ("POST", "/v1/messages"),
    ("POST", "/v1/messages/count_tokens"),
    ("POST", "/v1/chat/completions"),
    ("POST", "/api/event_logging/batch"),
}

_SCAN_PATTERN = re.compile(
    r"("
    r"\.env"
    r"|\.git"
    r"|\.(?:php|asp|aspx|jsp|sql|bak|old|swp)"
    r"|\.(?:tar\.gz|zip|rar|7z)"
    r"|/wp-(?:admin|login|content|includes)"
    r"|phpmyadmin"
    r"|/\.(?:ssh|aws|docker|npmrc|htpasswd)"
    r"|/actuator|/_next/|/api/heartbeat"
    r"|/boaform|/manager/html|/jenkins|/owa"
    r")",
    re.IGNORECASE,
)


def _classify(path: str) -> str:
    return "scan" if _SCAN_PATTERN.search(path) else "unknown"


def _resolve_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "-"


@asynccontextmanager
async def lifespan(app: FastAPI):
    frames = settings.tracemalloc_frames
    if frames > 0 and not tracemalloc.is_tracing():
        tracemalloc.start(frames)
        print(f"  tracemalloc: enabled ({frames} frames)")
    else:
        print(f"  tracemalloc: disabled")

    print("Starting deepseek-vision proxy")
    print(f"  Port: {settings.port}")
    try:
        from app import slow_log
        slow_log.cleanup_old_dumps()
    except Exception:
        pass
    yield
    print("Shutting down")
    if tracemalloc.is_tracing():
        tracemalloc.stop()


app = FastAPI(
    title="deepseek-vision",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_ALLOWED_PATHS = {path for _, path in ALLOWED_ROUTES}


@app.middleware("http")
async def whitelist_middleware(request: Request, call_next):
    method = request.method
    path = request.url.path

    if method == "OPTIONS":
        return await call_next(request)

    if (method, path) in ALLOWED_ROUTES:
        return await call_next(request)

    if method == "HEAD":
        return Response(status_code=200)

    ip = _resolve_ip(request)
    ua = request.headers.get("user-agent", "-")[:80]
    tag = _classify(path)
    _scan_logger.info(f'[SCAN] {method} {path} tag={tag} ip={ip} ua="{ua}"')
    return Response(status_code=404, content="Not Found", media_type="text/plain")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(messages_router, prefix="/v1")
app.include_router(models_router, prefix="/v1")

from app.openai_compat import router as openai_router
app.include_router(openai_router, prefix="/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/event_logging/batch")
async def event_logging():
    return {"status": "ok"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(
            status_code=exc.status_code,
            content={"type": "error", "error": exc.detail},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"type": "error", "error": {"type": "api_error", "message": str(exc.detail)}},
    )
