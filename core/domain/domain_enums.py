"""主动调度触发来源。"""

from __future__ import annotations

from enum import Enum


class TriggerSource(Enum):
    SCHEDULE = "schedule"
    AUTO_TRIGGER = "auto_trigger"
    GROUP_IDLE = "group_idle"
    MANUAL = "manual"
