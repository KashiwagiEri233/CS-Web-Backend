"""触发各类异常的联调端点，用于验证异常处理器 / 异常日志链路。

**仅在 DEBUG=True 时挂载**（见 ``app/api/v1/__init__.py`` 末尾的条件 include）：
生产环境这些路由根本不会注册，所以函数体内无需再逐个判断 settings.DEBUG——
那层守卫是条件挂载之前的遗留，现已是死代码。

放在 app/api/v1/ 下是为了让异常处理器能沿真实请求链路端到端触发。
"""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/test-exception")
async def test_exception():
    """触发未捕获异常（走兜底 500 处理器）"""
    raise ValueError("这是一个测试异常")


@router.get("/test-http-exception")
async def test_http_exception():
    """触发 HTTP 异常"""
    raise HTTPException(status_code=400, detail="这是一个测试HTTP异常")


@router.post("/test-validation-exception")
async def test_validation_exception(data: dict):
    """触发请求体验证异常：请求体传非对象的 JSON 即得 422"""
    return {"received": data}


@router.get("/test-zero-division")
async def test_zero_division():
    """触发内建异常（ZeroDivisionError）"""
    return {"result": 1 / 0}
