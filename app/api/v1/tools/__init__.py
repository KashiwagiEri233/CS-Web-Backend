"""tools 业务域路由包（考试/资源/任务/积分/组件注册表/功能可见性）。

2026-08-19 模块化重构：tools 子域从 api/v1 平铺收编为包，
路由前缀不变（/tools，feature_visibility 无前缀），契约零变化。
"""

from app.api.v1.tools import (
    component_registry,
    exam,
    feature_visibility,
    points,
    resource,
    task,
)

__all__ = [
    "component_registry",
    "exam",
    "feature_visibility",
    "points",
    "resource",
    "task",
]
