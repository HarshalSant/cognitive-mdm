"""
CognitiveMDM API Gateway
Unified entry point with JWT auth, RBAC, rate limiting, and reverse proxy.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, Histogram, make_asgi_app

from .middleware.auth import AuthMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .routes import entities, graph, governance, agents, copilot, ingestion, health

logger = structlog.get_logger(__name__)

REQUEST_COUNT = Counter(
    "api_gateway_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "api_gateway_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("api_gateway.starting", version="1.0.0")
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    yield
    await app.state.http_client.aclose()
    logger.info("api_gateway.stopped")


app = FastAPI(
    title="CognitiveMDM API",
    description="AI-Native Master Data Management Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ─── Middleware ───────────────────────────────────────────────

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=1000)


@app.middleware("http")
async def telemetry_middleware(request: Request, call_next) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start

    endpoint = request.url.path
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status_code=response.status_code,
    ).inc()
    REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(elapsed)

    response.headers["X-Response-Time"] = f"{elapsed * 1000:.2f}ms"
    response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", "")
    return response


# ─── Routes ──────────────────────────────────────────────────

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(entities.router, prefix="/api/v1/entities", tags=["entities"])
app.include_router(graph.router, prefix="/api/v1/graph", tags=["graph"])
app.include_router(governance.router, prefix="/api/v1/governance", tags=["governance"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(copilot.router, prefix="/api/v1/copilot", tags=["copilot"])
app.include_router(ingestion.router, prefix="/api/v1/ingestion", tags=["ingestion"])

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

FastAPIInstrumentor.instrument_app(app)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "message": "An unexpected error occurred"},
    )
