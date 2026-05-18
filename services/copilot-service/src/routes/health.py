from fastapi import APIRouter
router = APIRouter()

@router.get("/live")
async def live():
    return {"status": "ok", "service": "copilot-service"}

@router.get("/ready")
async def ready():
    return {"status": "ok", "service": "copilot-service"}
