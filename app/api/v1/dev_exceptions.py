"""
开发期异常日志联调端点。

位置说明：本文件放在 app/api/v1/ 是为了让异常处理器能真实端到端触发，
便于开发期联调。**仅在 DEBUG=True 时挂载**（见 app/api/v1/__init__.py），
生产环境（DEBUG=False）下路由不存在，直接 404。

命名说明：文件名刻意不含 test_ 前缀，避免被 pytest 默认收集规则
（test_*.py）误判为测试模块。
"""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/test-exception")
async def test_exception():
    """测试异常日志记录"""
    raise ValueError("这是一个测试异常")


@router.get("/test-http-exception")
async def test_http_exception():
    """测试HTTP异常日志记录"""
    raise HTTPException(status_code=400, detail="这是一个测试HTTP异常")


@router.post("/test-validation-exception")
async def test_validation_exception(data: dict):
    """测试验证异常日志记录（body 无 schema 约束，用于触发自定义验证流程）"""
    return {"echo": data}


@router.get("/test-zero-division")
async def test_zero_division():
    """测试除零异常日志记录"""
    result = 1 / 0
    return {"result": result}
