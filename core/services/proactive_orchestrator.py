"""主动调度到 Personal Runtime 的最小编排层。"""

from __future__ import annotations

from typing import Any

from astrbot.api import logger

from ..domain.domain_enums import TriggerSource
from ..domain.session_key import is_friend_type


class ProactiveOrchestrator:
    """把调度触发转换为 Runtime Observation，不生成或发送回复。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    async def run(
        self,
        session_id: str,
        trigger: TriggerSource = TriggerSource.SCHEDULE,
    ) -> None:
        plugin = self.plugin
        if getattr(plugin, "_terminating", False):
            logger.debug("[主动消息] 插件正在终止，跳过本次主动事实喵。")
            return

        normalized = plugin.session_service.normalize_session_id(session_id)
        try:
            session_config = plugin.config_service.get_session_config(normalized)
            if not session_config or not session_config.get("enable", False):
                async with plugin.data_lock:
                    if plugin.scheduler_service.clear_session_schedule_state(normalized):
                        await plugin.storage_service.save_data()
                logger.info(
                    "[主动消息] 会话已禁用或配置不存在，清理主动任务：session=%s",
                    normalized,
                )
                return

            submission = await plugin.personal_runtime_bridge.submit_due(
                normalized,
                trigger=trigger,
                session_config=session_config,
            )
            parsed = plugin.session_service.parse_session_id(normalized)
            if not submission.admitted and submission.retryable:
                logger.warning(
                    "[主动消息] Personal Runtime 未接纳主动事实，已重新排期：session=%s trigger=%s reason=%s",
                    normalized,
                    trigger.value,
                    submission.reason,
                )
                await plugin.scheduler_service.schedule_next_chat_and_save(
                    normalized,
                )
            elif submission.admitted and parsed and is_friend_type(parsed[1]):
                await plugin.scheduler_service.schedule_next_chat_and_save(
                    normalized,
                )
            else:
                if not submission.admitted:
                    logger.info(
                        "[主动消息] Personal Runtime 已终止接纳本次事实，清理当前任务：session=%s status=%s reason=%s",
                        normalized,
                        submission.status,
                        submission.reason,
                    )
                async with plugin.data_lock:
                    if plugin.scheduler_service.clear_session_schedule_state(normalized):
                        await plugin.storage_service.save_data()

            logger.info(
                "[主动消息] 已将主动事实交给 Personal Runtime：session=%s admitted=%s status=%s trigger=%s",
                normalized,
                submission.admitted,
                submission.status,
                trigger.value,
            )
        except Exception:
            logger.exception(
                "[主动消息] Personal Runtime 主动事实提交失败：session=%s",
                normalized,
            )
            try:
                await plugin.scheduler_service.schedule_next_chat_and_save(
                    normalized,
                )
            except Exception:
                logger.exception(
                    "[主动消息] 主动事实失败后的重新排期失败：session=%s",
                    normalized,
                )
        finally:
            await self.clear_manual_trigger_state(normalized)

    async def clear_manual_trigger_state(self, session_id: str) -> None:
        normalized = self.plugin.session_service.normalize_session_id(session_id)
        self.plugin.manual_trigger_sessions.discard(normalized)


__all__ = ["ProactiveOrchestrator"]
