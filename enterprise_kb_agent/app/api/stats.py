from fastapi import APIRouter

from app.core.logger import get_query_logger
from app.schemas.chat import StatsData
from app.utils.response import success_response


router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_stats():
    data = get_query_logger().get_stats()
    return success_response(StatsData(**data).model_dump())

