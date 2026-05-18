FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.109.0 uvicorn[standard]==0.27.0 \
    neo4j==5.15.0 structlog==24.1.0 \
    pydantic==2.6.0 aiokafka==0.10.0

COPY src/ src/

EXPOSE 8004

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8004", "--workers", "2"]
