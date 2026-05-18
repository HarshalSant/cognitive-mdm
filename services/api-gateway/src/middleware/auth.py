"""
JWT authentication and RBAC middleware for the API Gateway.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

# Endpoints that bypass authentication
PUBLIC_PATHS = {
    "/health",
    "/health/live",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
}

# RBAC: role -> allowed path prefixes
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["/api/v1"],
    "data_steward": [
        "/api/v1/entities",
        "/api/v1/graph",
        "/api/v1/governance",
        "/api/v1/ingestion",
    ],
    "analyst": [
        "/api/v1/entities",
        "/api/v1/graph",
        "/api/v1/copilot",
    ],
    "agent_runner": ["/api/v1/agents"],
    "readonly": ["/api/v1/entities", "/api/v1/graph"],
}


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def check_permission(role: str, path: str) -> bool:
    allowed = ROLE_PERMISSIONS.get(role, [])
    return any(path.startswith(prefix) for prefix in allowed)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PATHS):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "missing_token", "message": "Authorization header required"},
            )

        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_token(token)
        except JWTError as e:
            logger.warning("auth.invalid_token", error=str(e))
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "message": "Token is invalid or expired"},
            )

        role = payload.get("role", "readonly")
        if not check_permission(role, path):
            logger.warning("auth.forbidden", path=path, role=role, user=payload.get("sub"))
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "message": f"Role '{role}' cannot access {path}"},
            )

        request.state.user = payload
        request.state.user_id = payload.get("sub")
        request.state.role = role
        return await call_next(request)
