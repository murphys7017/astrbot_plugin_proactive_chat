"""主动调度领域契约。"""

from .domain_enums import TriggerSource
from .session_key import (
    SessionKey,
    contains_group_marker,
    is_friend_type,
    is_group_type,
    is_group_umo,
)

__all__ = [
    "SessionKey",
    "TriggerSource",
    "contains_group_marker",
    "is_friend_type",
    "is_group_type",
    "is_group_umo",
]
