from typing import Any, Optional


def success_response(data: Any = None, message: str = "success", code: int = 200) -> dict:
    return {
        "code": code,
        "message": message,
        "data": data if data is not None else {},
    }


def error_response(message: str, code: int = 500, data: Optional[Any] = None) -> dict:
    return {
        "code": code,
        "message": message,
        "data": data,
    }

