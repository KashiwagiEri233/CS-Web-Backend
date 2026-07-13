"""
测试异常日志记录的 API 端点。

位置说明：本文件放在 app/api/v1/ 是为了让异常处理器能真实端到端触发，
便于开发期联调。**所有端点均有 DEBUG 守护**：生产环境（DEBUG=False）
下统一返回 404，不会暴露给外部。如需彻底隔离，可改用条件挂载：
    if settings.DEBUG:
        api_router.include_router(test_exceptions.router, ...)
"""

from fastapi import APIRouter, HTTPException
from app.core.config import settings

router = APIRouter()


@router.get("/test-exception")
async def test_exception():
    """测试异常日志记录"""
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not Found")
    raise ValueError("这是一个测试异常")


@router.get("/test-http-exception")
async def test_http_exception():
    """测试HTTP异常日志记录"""
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not Found")
    raise HTTPException(status_code=400, detail="这是一个测试HTTP异常")


@router.post("/test-validation-exception")
async def test_validation_exception(data: dict):
    """测试验证异常日志记录"""
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not Found")
    pass


@router.get("/test-zero-division")
async def test_zero_division():
    """测试除零异常日志记录"""
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not Found")
    result = 1 / 0
    return {"result": result}
