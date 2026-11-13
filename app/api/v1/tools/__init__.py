"""tools 业务域路由包（考试/资源/组件注册表/功能可见性）。

2026-08-19 模块化重构：tools 子域从 api/v1 平铺收编为包，
路由前缀不变（/tools，feature_visibility 无前缀），契约零变化。
2026-11-09：旧任务代理与旧积分入口已随统一任务/钱包契约移除。
"""

from app.api.v1.tools import (
    component_registry,
    exam,
    feature_visibility,
    resource,
)

__all__ = [
    "component_registry",
    "exam",
    "feature_visibility",
    "resource",
]
