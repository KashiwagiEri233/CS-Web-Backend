"""API 出参基类。

双时区约定（见 CLAUDE.md）：核心/存储一律 UTC，对外展示用 settings.TIMEZONE。
本基类在**序列化边界**统一把 datetime 字段从 UTC 转为本地时区并输出 ISO 字符串，
这样路由层/服务层无需逐处手动转换——凡是出参模型继承 TZModel 即自动本地化。

实现要点：
- ``field_serializer("*", mode="wrap")`` 拦截所有字段：是 datetime 就转本地后输出 ISO，
  其它字段（含嵌套 BaseModel、list）走 ``handler`` 正常序列化，保证嵌套模型不被破坏。
- **始终返回 str**（而非 datetime 对象）：错误响应路径用 python 模式 ``model_dump()`` 后直接
  交给 Starlette ``JSONResponse``，其 ``json.dumps`` 不认 datetime；返回 str 同时兼容
  FastAPI response_model 的 json 模式与该 python 模式两条路径。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.timezone import utc_to_local


class TZModel(BaseModel):
    """出参基类：from_attributes + datetime 统一转 settings.TIMEZONE 展示。"""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", mode="wrap", when_used="always")
    def _serialize_local_datetime(self, value, handler):
        if isinstance(value, datetime):
            local = utc_to_local(value)
            return local.isoformat() if local is not None else None
        return handler(value)
