"""API 认证依赖，用于保护需要授权的端点."""

from fastapi import HTTPException, Request

from app.core.config import settings


async def require_api_key(request: Request) -> None:
    """验证请求中的 API Key。未配置时允许所有请求通过（开发模式）。"""
    if not settings.operations_api_key:
        # 未配置 API Key 时允许通过（开发/演示模式）
        return

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
    else:
        token = request.headers.get("X-API-Key", "")

    if not token or token != settings.operations_api_key:
        raise HTTPException(status_code=401, detail="无效或缺失的 API Key。请在 Authorization 头中传递 Bearer <key>，或使用 X-API-Key 头。")
