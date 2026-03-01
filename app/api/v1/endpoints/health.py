from fastapi import APIRouter

from app.core.responses import success_response

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    return success_response(data={"status": "ok"}, message="Service is healthy")
