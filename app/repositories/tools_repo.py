"""向后兼容 shim：实现已迁移至 ``app.repositories.tools`` 子包。

C-18 repo 巨型文件拆分第二切片（tools_repo.py 635 行 → 5 个子模块 + 1 私有 helper）。
调用方 ``from app.repositories.tools_repo import XxxRepository`` 继续可用，
待 C-17 服务层改造收口后随调用方 import 路径一并清理本文件。
"""

from app.repositories.tools import (
    ComponentRegistryRepository,
    ExamRepository,
    PointsRepository,
    ResourceRepository,
    TaskRepository,
)

__all__ = [
    "ComponentRegistryRepository",
    "ExamRepository",
    "PointsRepository",
    "ResourceRepository",
    "TaskRepository",
]