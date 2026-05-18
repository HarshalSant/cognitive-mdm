FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml 2>/dev/null || pip install --no-cache-dir \
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    httpx==0.26.0 \
    python-jose[cryptography]==3.3.0 \
    redis[asyncio]==5.0.1 \
    structlog==24.1.0 \
    pydantic==2.6.0 \
    prometheus-client==0.19.0 \
    opentelemetry-sdk==1.22.0 \
    opentelemetry-instrumentation-fastapi==0.43b0

COPY src/ src/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
