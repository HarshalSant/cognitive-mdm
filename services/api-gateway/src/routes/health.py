from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/live", response_model=HealthResponse)
async def liveness():
    return HealthResponse(status="ok", service="api-gateway", version="1.0.0")


@router.get("/ready", response_model=HealthResponse)
async def readiness():
    return HealthResponse(status="ok", service="api-gateway", version="1.0.0")
