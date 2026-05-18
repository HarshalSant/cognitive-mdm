FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.109.0 uvicorn[standard]==0.27.0 \
    sentence-transformers==2.3.1 \
    qdrant-client==1.7.3 \
    anthropic==0.18.1 \
    structlog==24.1.0 pydantic==2.6.0

COPY src/ src/

EXPOSE 8003

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "1"]
