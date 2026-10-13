"""工具集仓储子包：考试 / 资源 / 任务 / 积分 / 组件注册表。

各仓储类按职责拆分至同目录子模块，此处统一重新导出以简化调用方 import。
原 ``app.repositories.tools_repo`` 已降级为指向本子包的兼容 shim。
"""

from app.repositories.tools.component_registry import ComponentRegistryRepository
from app.repositories.tools.exam import ExamRepository
from app.repositories.tools.points import PointsRepository
from app.repositories.tools.resource import ResourceRepository
from app.repositories.tools.task import TaskRepository

__all__ = [
    "ComponentRegistryRepository",
    "ExamRepository",
    "PointsRepository",
    "ResourceRepository",
    "TaskRepository",
]