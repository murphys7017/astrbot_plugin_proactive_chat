"""AstrBot 插件页面的轻量运行时 API。"""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger

from ..domain.domain_enums import TriggerSource
from .state_builder import StateBuilder


PLUGIN_NAME = "astrbot_plugin_proactive_chat"


class PluginViewService:
    """把主动消息的运行态操作注册到 AstrBot Dashboard。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.state = StateBuilder(plugin, getattr(plugin, "version", ""))
        self._register_routes()

    def _register_routes(self) -> None:
        context = self.plugin.context
        prefix = f"/{PLUGIN_NAME}"
        context.register_web_api(
            f"{prefix}/status", self.get_status, ["GET"], "主动消息运行状态"
        )
        context.register_web_api(
            f"{prefix}/jobs", self.get_jobs, ["GET"], "主动消息调度任务"
        )
        context.register_web_api(
            f"{prefix}/sessions", self.get_sessions, ["GET"], "主动消息会话"
        )
        context.register_web_api(
            f"{prefix}/jobs/<umo>/trigger",
            self.trigger_job,
            ["POST"],
            "立即触发主动消息",
        )
        context.register_web_api(
            f"{prefix}/jobs/<umo>/reschedule",
            self.reschedule_job,
            ["POST"],
            "重新安排主动消息任务",
        )
        context.register_web_api(
            f"{prefix}/jobs/<umo>/cancel",
            self.cancel_job,
            ["POST"],
            "取消主动消息任务",
        )

    async def get_status(self) -> dict[str, Any]:
        return await self.state.build_status_payload()

    async def get_jobs(self) -> dict[str, Any]:
        return {"jobs": self.state.collect_jobs()}

    async def get_sessions(self) -> dict[str, Any]:
        return {"sessions": self.state.list_known_session_summaries()}

    async def trigger_job(self, umo: str) -> dict[str, Any]:
        plugin = self.plugin
        normalized = plugin.session_service.normalize_session_id(umo)
        if normalized in plugin.manual_trigger_sessions:
            return {
                "ok": False,
                "session": normalized,
                "in_progress": True,
                "message": "该任务正在触发中，请等待当前执行完成",
            }

        plugin.manual_trigger_sessions.add(normalized)
        plugin._track_task(
            asyncio.create_task(
                plugin.check_and_chat(normalized, trigger=TriggerSource.MANUAL)
            )
        )
        return {
            "ok": True,
            "session": normalized,
            "in_progress": True,
            "message": "已开始触发",
        }

    async def reschedule_job(self, umo: str) -> dict[str, Any]:
        plugin = self.plugin
        normalized = plugin.session_service.normalize_session_id(umo)
        session_config = plugin.config_service.get_session_config(normalized)
        if not session_config or not session_config.get("enable", False):
            return {
                "ok": False,
                "session": normalized,
                "message": "会话未启用或配置不存在",
            }

        await plugin.scheduler_service.schedule_next_chat_and_save(
            normalized, reset_counter=False
        )
        return {"ok": True, "session": normalized}

    async def cancel_job(self, umo: str) -> dict[str, Any]:
        plugin = self.plugin
        normalized = plugin.session_service.normalize_session_id(umo)
        removed = False
        try:
            if plugin.scheduler:
                plugin.scheduler.remove_job(normalized)
                removed = True
        except Exception as e:  # noqa: BLE001 - 取消是幂等操作
            logger.debug(f"[主动消息] 插件页面取消任务时未找到调度任务喵: {e}")

        if plugin.data_lock:
            async with plugin.data_lock:
                if normalized in plugin.session_data:
                    plugin.session_data[normalized].pop("next_trigger_time", None)
                    await plugin.storage_service.save_data()

        return {"ok": True, "session": normalized, "removed": removed}


__all__ = ["PluginViewService"]
