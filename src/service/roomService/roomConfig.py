"""房间级共享配置解析（叶子模块，无循环依赖）。

ChatRoom、RoomScheduler、roomService.core 三方都需要"解析房间最大轮次"，
但该 helper 不能放在它们任一模块内（会构成循环导入）。独立成叶子模块，
仅依赖 util，供各层安全引用。
"""
from __future__ import annotations

from util import configUtil


def resolve_room_max_rounds(max_rounds: int | None) -> int:
    """解析房间最大轮次：显式配置优先，缺省回落到全局 default_room_max_rounds。"""
    if max_rounds is not None:
        return max_rounds
    return configUtil.get_app_config().setting.default_room_max_rounds
