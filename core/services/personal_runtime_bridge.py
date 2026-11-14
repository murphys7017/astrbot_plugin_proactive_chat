"""Personal Runtime 适配层。

主动消息插件只提交结构化事实；最终是否表达、如何生成回复和如何发送，
统一交给 AstrBot 的 Personal Runtime。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astrbot.api import logger

from ..domain.domain_enums import TriggerSource


@dataclass(frozen=True, slots=True)
class ProactiveObservationSensor:
    plugin_id: str = "astrbot_plugin_proactive_chat"
    source_id: str = "scheduled_proactive_message"


class PersonalRuntimeBridge:
    """把主动调度事件投递到宿主 Personal Runtime。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        register = getattr(plugin.context, "register_runtime_observation_sensor", None)
        self._handle = register(ProactiveObservationSensor()) if callable(register) else None
        if self._handle is None:
            logger.warning(
                "[主动消息] 当前 AstrBot 未提供 Runtime Observation Sensor，"
                "主动消息不会绕过 Personal 直接发送。"
            )

    async def submit_due(
        self,
        session_id: str,
        *,
        trigger: TriggerSource,
        session_config: dict[str, Any] | None,
        unanswered_count: int = 0,
    ) -> bool:
        """提交一次主动事实，不生成用户可见文本。"""
        if self._handle is None:
            return False

        session_type = ""
        if isinstance(session_config, dict):
            session_type = str(session_config.get("_session_type") or "")

        payload = {
            "trigger": trigger.value,
            "session_type": session_type,
            "unanswered_count": max(0, int(unanswered_count)),
        }
        try:
            result = await self._handle.submit(
                kind="proactive_schedule_due",
                session=session_id,
                payload=payload,
                expires_in_seconds=180.0,
                coalesce_key="schedule_due",
            )
        except Exception as exc:  # noqa: BLE001 - 事实投递失败需回到调度兜底
            logger.warning(
                "[主动消息] Personal Runtime 事实投递失败：session=%s error=%s",
                session_id,
                exc,
            )
            return False

        return bool(getattr(result, "admitted", result is not None))


__all__ = ["PersonalRuntimeBridge", "ProactiveObservationSensor"]
