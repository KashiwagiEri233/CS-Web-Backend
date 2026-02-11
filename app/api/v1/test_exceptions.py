"""
测试异常日志记录的API端点
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

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
    """测试验证异常日志记录"""
    # 这个请求会自动触发验证异常
    pass

@router.get("/test-zero-division")
async def test_zero_division():
    """测试除零异常日志记录"""
    result = 1 / 0
    return {"result": result}