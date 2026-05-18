FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.109.0 uvicorn[standard]==0.27.0 \
    sqlalchemy[asyncio]==2.0.25 asyncpg==0.29.0 \
    qdrant-client==1.7.3 sentence-transformers==2.3.1 \
    rapidfuzz==3.6.1 jellyfish==1.0.3 \
    anthropic==0.18.1 aiokafka==0.10.0 \
    structlog==24.1.0 pydantic==2.6.0 \
    prometheus-client==0.19.0 numpy==1.26.3

COPY src/ src/

EXPOSE 8002

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "2"]
