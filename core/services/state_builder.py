"""AstrBot 插件页面的运行状态载荷构建。"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any

from ..domain.session_key import is_group_type, is_group_umo


class StateBuilder:
    """构建运行状态、任务卡片、会话摘要与文档列表载荷。"""

    def __init__(self, plugin: Any, metadata_version: str) -> None:
        self.plugin = plugin
        self._metadata_version = metadata_version

    # ------------------------------------------------------------------
    # 计时器元信息
    # ------------------------------------------------------------------
    def safe_timer_meta(self, timer: Any, now: float) -> dict[str, float | int | None]:
        """安全读取 asyncio 计时器的剩余时间与绝对目标时间。

        计时器可能已取消、已完成或实现不完整，统一用 None 表示“不可用”，
        避免异常向上冒泡导致状态载荷构建失败。
        """
        if timer is None:
            return {"remaining_seconds": None, "target_time": None}

        try:
            if getattr(timer, "cancelled", lambda: False)():
                return {"remaining_seconds": None, "target_time": None}
        except Exception:
            return {"remaining_seconds": None, "target_time": None}

        when_method = getattr(timer, "when", None)
        if not callable(when_method):
            return {"remaining_seconds": None, "target_time": None}

        try:
            loop_time = when_method()
            loop = getattr(timer, "_loop", None)
            current_loop_time = loop.time() if loop else None
            if current_loop_time is None:
                return {"remaining_seconds": None, "target_time": None}

            remaining_precise = max(0.0, loop_time - current_loop_time)
            target_time = now + remaining_precise
            return {
                "remaining_seconds": max(0, int(math.ceil(remaining_precise))),
                "target_time": target_time,
            }
        except Exception:
            return {"remaining_seconds": None, "target_time": None}

    def detect_session_category(self, session_id: str) -> str:
        """判断会话属于群聊还是私聊，用于前端展示分类。"""
        parsed = self.plugin.session_service.parse_session_id(session_id)
        if not parsed:
            return "group" if is_group_umo(str(session_id)) else "friend"

        _, msg_type, _ = parsed
        return "group" if is_group_type(msg_type) else "friend"

    # ------------------------------------------------------------------
    # 计时器卡片
    # ------------------------------------------------------------------
    def collect_timer_cards(self, now: float) -> dict[str, list[dict[str, Any]]]:
        """收集自动触发与群聊沉默两类计时器卡片。

        群聊会话由沉默计时器驱动；若同一会话同时存在自动触发计时器，
        则以群聊卡片为准去重，避免重复展示。
        """
        plugin = self.plugin
        auto_cards: list[dict[str, Any]] = []
        group_cards: list[dict[str, Any]] = []
        # 记录已有群聊沉默计时器的会话，稍后据此过滤自动触发卡片。
        active_group_sessions = {
            str(session_id) for session_id in plugin.group_timers.keys()
        }

        for session_id, timer in list(plugin.auto_trigger_timers.items()):
            normalized_session_id = plugin.session_service.normalize_session_id(
                str(session_id)
            )
            # 该会话已由群聊沉默计时器接管，跳过自动触发卡片。
            if normalized_session_id in active_group_sessions:
                continue

            session_config = plugin.config_service.get_session_config(session_id) or {}
            session_data = plugin.session_data.get(session_id, {})
            auto_settings = session_config.get("auto_trigger_settings", {})
            schedule_settings = session_config.get("schedule_settings", {})
            trigger_delay_minutes = int(
                auto_settings.get("auto_trigger_after_minutes", 0) or 0
            )
            trigger_delay_seconds = max(0, trigger_delay_minutes * 60)
            timer_meta = self.safe_timer_meta(timer, now)
            remaining_seconds = timer_meta["remaining_seconds"]
            target_time = timer_meta["target_time"]
            started_at = max(plugin.plugin_start_time, now - trigger_delay_seconds)
            progress_percent = 0
            # 按“总窗口 - 剩余时间”估算已消耗进度，供前端进度条使用。
            if trigger_delay_seconds > 0 and remaining_seconds is not None:
                consumed = max(0, trigger_delay_seconds - remaining_seconds)
                progress_percent = max(
                    0, min(100, round((consumed / trigger_delay_seconds) * 100))
                )

            auto_cards.append(
                {
                    "session_id": normalized_session_id,
                    "session_name": plugin.session_service.get_session_name(
                        normalized_session_id, session_config
                    ),
                    "session_display_name": plugin.session_service.get_session_display_name(
                        normalized_session_id, session_config
                    ),
                    "session_category": self.detect_session_category(
                        normalized_session_id
                    ),
                    "quiet_hours": schedule_settings.get("quiet_hours", ""),
                    "quiet_hours_enabled": bool(
                        schedule_settings.get("enable_quiet_hours", True)
                    ),
                    "timer_kind": "auto_trigger",
                    "title": "自动触发检测",
                    "status": "running" if remaining_seconds is not None else "unknown",
                    "remaining_seconds": remaining_seconds,
                    "target_time": target_time,
                    "started_at": started_at,
                    "window_seconds": trigger_delay_seconds,
                    "progress_percent": progress_percent,
                    "auto_trigger_after_minutes": trigger_delay_minutes,
                }
            )

        # 群聊沉默计时器卡片（以用户最后发言时间为起点）。
        for session_id, timer in list(plugin.group_timers.items()):
            normalized_session_id = plugin.session_service.normalize_session_id(
                str(session_id)
            )
            session_config = (
                plugin.config_service.get_session_config(normalized_session_id) or {}
            )
            session_data = plugin.session_data.get(normalized_session_id, {})
            schedule_settings = session_config.get("schedule_settings", {})
            idle_minutes = int(session_config.get("group_idle_trigger_minutes", 0) or 0)
            idle_seconds = max(0, idle_minutes * 60)
            timer_meta = self.safe_timer_meta(timer, now)
            remaining_seconds = timer_meta["remaining_seconds"]
            target_time = timer_meta["target_time"]
            last_message_time = plugin.last_message_times.get(normalized_session_id, 0)
            temp_state = plugin.session_temp_state.get(normalized_session_id, {})
            # 优先级：人为重新计时的起点 > 真实发言时间 > 临时状态。
            # 重新计时不再改写 last_message_times，卡片必须从独立起点读，
            # 否则工期展示会跳回旧值。
            last_user_time = (
                plugin.silence_baselines.get(normalized_session_id)
                or last_message_time
                or temp_state.get("last_user_time")
                or None
            )
            started_at = last_user_time or (
                now - max(0, idle_seconds - (remaining_seconds or 0))
            )
            progress_percent = 0
            if idle_seconds > 0 and remaining_seconds is not None:
                consumed = max(0, idle_seconds - remaining_seconds)
                progress_percent = max(
                    0, min(100, round((consumed / idle_seconds) * 100))
                )

            group_cards.append(
                {
                    "session_id": normalized_session_id,
                    "session_name": plugin.session_service.get_session_name(
                        normalized_session_id, session_config
                    ),
                    "session_display_name": plugin.session_service.get_session_display_name(
                        normalized_session_id, session_config
                    ),
                    "session_category": self.detect_session_category(
                        normalized_session_id
                    ),
                    "quiet_hours": schedule_settings.get("quiet_hours", ""),
                    "quiet_hours_enabled": bool(
                        schedule_settings.get("enable_quiet_hours", True)
                    ),
                    "timer_kind": "group_silence",
                    "title": "群沉默检测",
                    "status": "running" if remaining_seconds is not None else "unknown",
                    "remaining_seconds": remaining_seconds,
                    "target_time": target_time,
                    "started_at": started_at if started_at else None,
                    "window_seconds": idle_seconds,
                    "progress_percent": progress_percent,
                    "group_idle_trigger_minutes": idle_minutes,
                    "last_message_time": last_message_time or None,
                    "last_user_time": last_user_time,
                    "is_live_group_timer": True,
                }
            )

        auto_cards.sort(
            key=lambda item: (
                item.get("remaining_seconds") is None,
                item.get("remaining_seconds") or 0,
                item["session_id"],
            )
        )
        group_cards.sort(
            key=lambda item: (
                item.get("remaining_seconds") is None,
                item.get("remaining_seconds") or 0,
                item["session_id"],
            )
        )
        return {
            "auto_trigger_cards": auto_cards,
            "group_timer_cards": group_cards,
        }

    # ------------------------------------------------------------------
    # 状态载荷
    # ------------------------------------------------------------------
    async def build_status_payload(self) -> dict[str, Any]:
        """构建运行状态载荷（版本、运行时长、任务计数与计时器卡片）。"""
        plugin = self.plugin
        now = time.time()
        uptime_sec = max(0, int(now - plugin.plugin_start_time))
        timer_cards = self.collect_timer_cards(now)
        return {
            "running": True,
            # timer_snapshot_at 是 remaining_seconds 对应的服务器时刻。
            # 前端据此扣除「构建 + 传输」耗时，否则刷新时会莫名少掉数秒。
            "timer_snapshot_at": now,
            "version": getattr(plugin, "version", None)
            or getattr(plugin, "__version__", None)
            or self._metadata_version
            or "未知版本",
            "uptime_seconds": uptime_sec,
            "uptime": str(
                datetime.fromtimestamp(now)
                - datetime.fromtimestamp(plugin.plugin_start_time)
            ),
            "scheduler_running": bool(plugin.scheduler and plugin.scheduler.running),
            "sessions_count": len(plugin.session_data),
            "auto_trigger_timers": len(plugin.auto_trigger_timers),
            "group_timers": len(plugin.group_timers),
            "jobs_count": len(plugin.scheduler.get_jobs()) if plugin.scheduler else 0,
            "timer_cards_total": len(timer_cards["auto_trigger_cards"])
            + len(timer_cards["group_timer_cards"]),
            "auto_trigger_cards": timer_cards["auto_trigger_cards"],
            "group_timer_cards": timer_cards["group_timer_cards"],
            # 时间戳用于前端判断数据新鲜度或手动刷新完成时间。
            "timestamp": datetime.now().isoformat(),
        }

    def collect_jobs(self) -> list[dict[str, Any]]:
        """收集 APScheduler 中已注册的主动消息任务摘要（不含人格，同步版）。"""
        return self._collect_jobs_sync()

    def _collect_jobs_sync(self) -> list[dict[str, Any]]:
        """任务摘要的同步构建实现，供异步版本复用。"""
        plugin = self.plugin
        if not plugin.scheduler:
            return []

        jobs = []
        for job in plugin.scheduler.get_jobs():
            session_id = str(job.id)
            session_data = plugin.session_data.get(session_id, {})
            session_config = plugin.config_service.get_session_config(session_id) or {}
            schedule_settings = session_config.get("schedule_settings", {})
            jobs.append(
                {
                    "id": session_id,
                    "session_name": plugin.session_service.get_session_name(
                        session_id, session_config
                    ),
                    "session_display_name": plugin.session_service.get_session_display_name(
                        session_id, session_config
                    ),
                    "session_category": self.detect_session_category(session_id),
                    "next_run_time": (
                        job.next_run_time.isoformat() if job.next_run_time else None
                    ),
                    "manual_trigger_in_progress": session_id
                    in plugin.manual_trigger_sessions,
                    "next_trigger_time": session_data.get("next_trigger_time"),
                    "last_scheduled_at": session_data.get("last_scheduled_at"),
                    "last_schedule_min_interval_seconds": session_data.get(
                        "last_schedule_min_interval_seconds"
                    ),
                    "last_schedule_max_interval_seconds": session_data.get(
                        "last_schedule_max_interval_seconds"
                    ),
                    "last_schedule_random_interval_seconds": session_data.get(
                        "last_schedule_random_interval_seconds"
                    ),
                    "schedule_min_interval_minutes": schedule_settings.get(
                        "min_interval_minutes"
                    ),
                    "schedule_max_interval_minutes": schedule_settings.get(
                        "max_interval_minutes"
                    ),
                    "quiet_hours": schedule_settings.get("quiet_hours", ""),
                    "quiet_hours_enabled": bool(
                        schedule_settings.get("enable_quiet_hours", True)
                    ),
                }
            )
        return jobs

    def list_known_sessions(self) -> list[str]:
        """汇总配置、会话数据与差异配置中出现过的所有会话标识。"""
        plugin = self.plugin
        sessions: set[str] = set()

        for scope_key in ("friend_settings", "group_settings"):
            cfg = plugin.config.get(scope_key, {})
            for session in cfg.get("session_list", []):
                if isinstance(session, str) and session:
                    sessions.add(plugin.session_service.normalize_session_id(session))

        sessions.update(plugin.session_data.keys())
        sessions.update(plugin.session_override_manager.list_sessions())
        return sorted(sessions)

    def list_known_session_summaries(self) -> list[dict[str, Any]]:
        """返回带展示信息的已知会话摘要（供 WS 实时推送使用）。"""
        plugin = self.plugin
        result: list[dict[str, Any]] = []
        for session in self.list_known_sessions():
            effective = plugin.config_service.get_session_config(session)
            result.append(
                {
                    "session": session,
                    "session_name": plugin.session_service.get_session_name(
                        session, effective
                    ),
                    "session_display_name": plugin.session_service.get_session_display_name(
                        session, effective
                    ),
                    "has_override": bool(
                        plugin.session_override_manager.get_override(session)
                    ),
                    "manual_trigger_in_progress": session
                    in plugin.manual_trigger_sessions,
                }
            )
        return result
