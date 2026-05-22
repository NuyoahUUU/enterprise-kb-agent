from fastapi import APIRouter, Depends

from app.core.auth import require_api_key
from app.schemas.operation import OperationExecuteData, OperationExecuteRequest
from app.services.operation_service import OperationService
from app.utils.response import success_response


router = APIRouter(tags=["operations"])
operation_service = OperationService()


@router.post("/operations/execute", dependencies=[Depends(require_api_key)])
def execute_operation(request: OperationExecuteRequest):
    data = operation_service.execute(request.operation)
    return success_response(OperationExecuteData(**data).model_dump())
