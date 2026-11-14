"""框架适配层：隔离 AstrBot 平台与会话 API。"""

from .astrbot_platform import (
    find_platform_by_id,
    iter_active_platform_instances,
    resolve_platform_instance,
)

__all__ = [
    "find_platform_by_id",
    "iter_active_platform_instances",
    "resolve_platform_instance",
]
