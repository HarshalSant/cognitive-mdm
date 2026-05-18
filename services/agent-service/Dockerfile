FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.109.0 uvicorn[standard]==0.27.0 \
    anthropic==0.18.1 httpx==0.26.0 \
    structlog==24.1.0 pydantic==2.6.0

COPY src/ src/

EXPOSE 8006

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8006", "--workers", "1"]
