"""插件生命周期服务。

由旧 core/plugin_lifecycle.py 等价搬迁而来。
"""

from __future__ import annotations

import asyncio
import time
import traceback
import zoneinfo
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from astrbot.api import logger

from ..adapters.astrbot_platform import iter_active_platform_instances


class LifecycleService:
    """插件初始化与终止清理服务。"""

    # 平台适配器就绪的最长等待时间与轮询间隔（秒）。
    STARTUP_PLATFORM_WAIT_TIMEOUT = 60.0
    STARTUP_PLATFORM_POLL_INTERVAL = 1.0

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    async def initialize(self) -> None:
        """插件的异步初始化函数。

        流程：初始化锁与状态 -> 加载数据 -> 解析时区 -> 启动调度器 ->
        依赖平台的恢复流程（平台未就绪时推迟）。
        """
        plugin = self.plugin
        # 复位容器的生命周期状态与并发锁。
        plugin._terminating = False
        plugin._startup_finalized = False
        plugin._startup_lock = asyncio.Lock()
        plugin._startup_task = None

        plugin.data_lock = asyncio.Lock()

        try:
            await plugin.config_service.validate_config()
        except Exception as e:
            logger.warning(
                f"[主动消息] 配置验证发现问题喵: {e}，将继续使用默认设置喵。"
            )

        # 加载持久化的会话数据。
        async with plugin.data_lock:
            await plugin.storage_service.load_data()
        logger.info("[主动消息] 已成功从文件加载会话数据喵。")

        # 解析时区；无效配置回退为服务器系统时区（None）。
        try:
            plugin.timezone = zoneinfo.ZoneInfo(
                plugin.context.get_config().get("timezone")
            )
        except (zoneinfo.ZoneInfoNotFoundError, TypeError, KeyError, ValueError) as e:
            logger.warning(
                f"[主动消息] 时区配置无效或未配置喵 ({e})，将使用服务器系统时区作为备用喵。"
            )
            plugin.timezone = None

        plugin.scheduler = AsyncIOScheduler(timezone=plugin.timezone)
        plugin.scheduler.start()

        # 平台就绪则立即恢复定时任务，否则推迟到 AstrBot 加载完成。
        if self.are_platforms_available():
            logger.debug("[主动消息] 平台适配器已就绪，立即恢复定时任务喵。")
            try:
                await self.finalize_startup()
            except Exception:
                logger.error(
                    f"[主动消息] 立即恢复定时任务失败喵，将转为延迟重试喵:\n"
                    f"{traceback.format_exc()}"
                )
                plugin._startup_task = asyncio.create_task(
                    self.wait_for_platforms_then_finalize()
                )
        else:
            logger.info(
                "[主动消息] 平台适配器尚未加载，定时任务恢复将推迟至 AstrBot 加载完成后执行喵。"
            )
            plugin._startup_task = asyncio.create_task(
                self.wait_for_platforms_then_finalize()
            )

    def are_platforms_available(self) -> bool:
        """判断是否已有可用的 IM 平台适配器实例。"""
        try:
            insts = iter_active_platform_instances(self.plugin.context.platform_manager)
        except Exception:
            return False
        return bool(insts)

    async def finalize_startup(self, *, allow_retry: bool = False) -> None:
        """在平台适配器就绪后完成依赖平台的启动流程。

        使用双重检查加锁，保证初始化的重活只执行一次；
        allow_retry 为 True 时不锁定完成标记，允许后续再次尝试。
        """
        plugin = self.plugin
        if plugin._startup_finalized or getattr(plugin, "_terminating", False):
            return

        async with plugin._startup_lock:
            if plugin._startup_finalized or getattr(plugin, "_terminating", False):
                return

            # 先规范化历史会话键，再恢复消息时间与调度任务。
            async with plugin.data_lock:
                if plugin.storage_service.normalize_session_data():
                    await plugin.storage_service.save_data()

            if getattr(plugin, "_terminating", False):
                return

            self.restore_last_message_times()

            await plugin.scheduler_service.init_jobs_from_data()
            logger.info("[主动消息] 调度器已初始化喵。")

            if getattr(plugin, "_terminating", False):
                return

            await plugin.scheduler_service.setup_auto_triggers_for_enabled_sessions()
            logger.info("[主动消息] 自动主动消息触发器初始化完成喵。")

            if not allow_retry:
                plugin._startup_finalized = True

    def restore_last_message_times(self) -> None:
        """从持久化数据恢复插件启动后的会话消息时间（用于自动触发判定）。"""
        plugin = self.plugin
        restored_count = 0
        for session_id, session_info in plugin.session_data.items():
            if not isinstance(session_info, dict):
                continue
            last_time = session_info.get("last_message_time")
            if not isinstance(last_time, (int, float)) or last_time <= 0:
                continue

            if last_time < plugin.plugin_start_time:
                logger.debug(
                    f"[主动消息] 忽略插件启动前的历史消息时间用于自动主动消息任务喵: "
                    f"{plugin.session_service.get_session_log_str(session_id)} -> {last_time}"
                )
                continue

            normalized_session_id = plugin.session_service.normalize_session_id(
                session_id
            )
            plugin.last_message_times[normalized_session_id] = last_time
            restored_count += 1
            logger.debug(
                f"[主动消息] 已恢复 {plugin.session_service.get_session_log_str(session_id)} "
                f"在插件启动后的消息时间喵 -> {last_time}"
            )

        if restored_count > 0:
            logger.info(
                f"[主动消息] 已从持久化数据恢复 {restored_count} 个会话在插件启动后的消息时间喵。"
            )

    async def on_astrbot_loaded(self) -> None:
        """AstrBot 加载完成回调：平台已加载，恢复持久化定时任务。"""

        try:
            await self.finalize_startup()
        except Exception:
            logger.error(
                f"[主动消息] AstrBot 加载完成钩子处理失败喵:\n{traceback.format_exc()}"
            )

    async def wait_for_platforms_then_finalize(self) -> None:
        """兜底等待平台加载后再完成任务恢复。

        超时后按当前可用平台尽力恢复（allow_retry），避免永久卡在等待态。
        """
        deadline = time.monotonic() + self.STARTUP_PLATFORM_WAIT_TIMEOUT
        try:
            while not self.are_platforms_available():
                if time.monotonic() >= deadline:
                    logger.warning(
                        "[主动消息] 等待平台适配器加载超时喵，将按当前可用平台尝试恢复定时任务喵。"
                    )
                    await self.finalize_startup(allow_retry=True)
                    return
                await asyncio.sleep(self.STARTUP_PLATFORM_POLL_INTERVAL)
            await self.finalize_startup()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error(
                f"[主动消息] 延迟恢复定时任务失败喵:\n{traceback.format_exc()}"
            )

    async def terminate(self) -> None:
        """插件被卸载或停用时调用的清理函数。

        顺序：置终止标记 -> 取消启动任务 -> 关闭调度器 -> 取消各类计时器 ->
        保存数据。
        """
        plugin = self.plugin
        logger.info("[主动消息] 收到插件终止指令，开始清理资源喵。")

        # 先置位终止标记，后续流程据此提前退出。
        plugin._terminating = True

        startup_task = getattr(plugin, "_startup_task", None)
        plugin._startup_task = None
        if startup_task and not startup_task.done():
            startup_task.cancel()

        # 关闭 APScheduler 并清理其注册的任务。
        if getattr(plugin, "scheduler", None) and plugin.scheduler.running:
            try:
                jobs = plugin.scheduler.get_jobs()
                plugin.scheduler.remove_all_jobs()
                logger.info(f"[主动消息] 已清理 {len(jobs)} 个调度器任务喵。")
                plugin.scheduler.shutdown(wait=False)
                logger.info("[主动消息] 调度器已关闭喵。")
            except Exception as e:
                logger.error(f"[主动消息] 关闭调度器时出错喵: {e}")

        # 取消所有群聊沉默计时器。
        timer_count = len(plugin.group_timers)
        for session_id, timer in list(plugin.group_timers.items()):
            try:
                timer.cancel()
            except Exception as e:
                logger.warning(f"[主动消息] 取消计时器时出错喵: {e}")
        plugin.group_timers.clear()
        logger.info(f"[主动消息] 已取消 {timer_count} 个正在运行的群聊沉默计时器喵。")

        # 取消所有自动触发计时器。
        auto_trigger_count = len(plugin.auto_trigger_timers)
        for session_id, timer in list(plugin.auto_trigger_timers.items()):
            try:
                timer.cancel()
            except Exception as e:
                logger.warning(f"[主动消息] 取消自动触发计时器时出错喵: {e}")
        plugin.auto_trigger_timers.clear()
        logger.info(f"[主动消息] 已取消 {auto_trigger_count} 个自动触发计时器喵。")

        # 按下述顺序收尾：等待启动任务 -> 保存数据。
        try:
            if startup_task:
                try:
                    await startup_task
                except asyncio.CancelledError:
                    pass

            await plugin._cleanup_tasks()

            if plugin.data_lock:
                try:
                    async with plugin.data_lock:
                        await plugin.storage_service.save_data()
                    logger.info("[主动消息] 会话数据已保存喵。")
                except Exception as e:
                    logger.error(f"[主动消息] 保存数据时出错喵: {e}")

        except Exception as e:
            logger.error(f"[主动消息] 生命周期终止阶段发生异常喵: {e}")
        finally:
            logger.info("[主动消息] 主动消息插件已终止喵。")
