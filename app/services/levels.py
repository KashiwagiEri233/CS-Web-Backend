"""等级阈值：由可用余额派生的成长等级（与前端 LEVEL_THRESHOLDS 对齐）。

P7 从旧积分服务迁出：统一钱包只按余额计算等级，不再维护第二套积分账本。
"""

from __future__ import annotations

from typing import TypedDict


class _LevelThreshold(TypedDict):
    level: int
    title: str
    min_points: int


LEVEL_THRESHOLDS: list[_LevelThreshold] = [
    {"level": 1, "title": "新手学徒", "min_points": 0},
    {"level": 2, "title": "初级成员", "min_points": 50},
    {"level": 3, "title": "活跃成员", "min_points": 150},
    {"level": 4, "title": "骨干成员", "min_points": 400},
    {"level": 5, "title": "核心骨干", "min_points": 1000},
    {"level": 6, "title": "技术专家", "min_points": 2500},
    {"level": 7, "title": "协会元老", "min_points": 5000},
]


def calculate_level(points: int) -> dict:
    """按余额返回等级与称号（最低等级兜底）。"""
    result = LEVEL_THRESHOLDS[0]
    for threshold in LEVEL_THRESHOLDS:
        if points >= threshold["min_points"]:
            result = threshold
    return {"level": result["level"], "title": result["title"]}
