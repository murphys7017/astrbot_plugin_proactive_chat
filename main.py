"""插件入口与装配容器。

主类只负责：装配各服务、注册 AstrBot 事件入口、承载容器级运行时状态。
具体业务逻辑分布在 services 中，主动事实统一交给宿主 Personal Runtime。
"""

from __future__ import annotations

import asyncio
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .core.adapters.event_handlers import EventHandlers
from .core.commands.plugin_command_service import PluginCommandService
from .core.domain.domain_enums import TriggerSource
from .core.services.config_service import ConfigService
from .core.services.lifecycle_service import LifecycleService
from .core.services.personal_runtime_bridge import PersonalRuntimeBridge
from .core.services.plugin_view_service import PluginViewService
from .core.services.proactive_orchestrator import ProactiveOrchestrator
from .core.services.scheduler_service import SchedulerService
from .core.services.session_service import SessionService
from .core.services.storage_service import StorageService
from .core.store.override_store import OverrideStore
from .utils.version_utils import get_plugin_version


class ProactiveChatPlugin(Star):
    """插件的主类：装配容器 + 事件入口 + 容器级状态。"""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)

        # 注入的配置对象（由 AstrBot 框架提供）
        self.config: AstrBotConfig = config
        # 调度器与时区会在 initialize 中初始化
        self.scheduler = None
        self.timezone = None

        # 使用 StarTools 获取插件专属数据目录（Path 对象）
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_proactive_chat")
        self.session_data_file = self.data_dir / "session_data.json"

        # 共享锁与持久化数据容器（data_lock 在 initialize 中初始化）
        self.data_lock = None
        self.session_data: dict = {}
        # 记录当前正在执行“立即触发”的会话，防止重复点击导致并发主动消息。
        self.manual_trigger_sessions: set[str] = set()

        self.version = get_plugin_version()

        # ------------------------------------------------------------------
        # 装配各服务（组合替代继承）
        # ------------------------------------------------------------------
        self.session_service = SessionService(self)
        self.storage_service = StorageService(self)
        self.config_service = ConfigService(self)
        self.scheduler_service = SchedulerService(self)
        self.lifecycle_service = LifecycleService(self)
        self.event_handlers = EventHandlers(self)
        self.orchestrator = ProactiveOrchestrator(self)
        self.personal_runtime_bridge = PersonalRuntimeBridge(self)
        # 指令层：main.py 只保留 @filter.command 薄壳，业务收敛在服务内。
        self.command_service = PluginCommandService(self)

        # 会话差异配置管理器
        self.session_override_manager = OverrideStore(self.data_dir)

        # AstrBot Dashboard 插件页面与运行时 API
        self.plugin_view_service = PluginViewService(self)

        self._task_refs: set[asyncio.Task[None]] = set()
        self._terminating = False

        # 平台就绪后的启动流程状态（延迟初始化，先占位）
        self._startup_finalized: bool = False
        self._startup_lock: asyncio.Lock | None = None
        self._startup_task: asyncio.Task[None] | None = None

        self.plugin_start_time = time.time()
        self._cleanup_counter = 0

        logger.info("[主动消息] 插件实例已创建喵。")

    # SchedulerService owns process-local timer state. These read-only views
    # preserve the existing service interfaces while keeping the container
    # from becoming a second state owner.
    @property
    def group_timers(self) -> dict[str, asyncio.TimerHandle]:
        return self.scheduler_service.runtime_state.group_timers

    @property
    def session_temp_state(self) -> dict[str, dict]:
        return self.scheduler_service.runtime_state.session_temp_state

    @property
    def last_message_times(self) -> dict[str, float]:
        return self.scheduler_service.runtime_state.last_message_times

    @property
    def auto_trigger_baselines(self) -> dict[str, float]:
        return self.scheduler_service.runtime_state.auto_trigger_baselines

    @property
    def silence_baselines(self) -> dict[str, float]:
        return self.scheduler_service.runtime_state.silence_baselines

    @property
    def auto_trigger_timers(self) -> dict[str, asyncio.TimerHandle]:
        return self.scheduler_service.runtime_state.auto_trigger_timers

    @property
    def first_message_logged(self) -> set[str]:
        return self.scheduler_service.runtime_state.first_message_logged

    # ==================================================================
    # 生命周期
    # ==================================================================
    async def initialize(self) -> None:
        """插件的异步初始化函数。"""
        await self.lifecycle_service.initialize()

    async def terminate(self) -> None:
        """插件终止入口。"""
        await self.lifecycle_service.terminate()

    def _track_task(self, task: asyncio.Task[None] | None) -> asyncio.Task[None] | None:
        """登记需要保留引用的后台任务。"""
        if task is None:
            return None
        self._task_refs.add(task)
        task.add_done_callback(self._task_refs.discard)
        return task

    async def _cleanup_tasks(self) -> None:
        """插件终止时取消仍在运行的生命周期任务。"""
        if not self._task_refs:
            return

        pending_tasks = list(self._task_refs)
        for task in pending_tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*pending_tasks, return_exceptions=True)
        self._task_refs.clear()

    # ==================================================================
    # 事件入口
    # ==================================================================
    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self) -> None:
        """AstrBot 加载完成钩子：平台已加载，恢复持久化定时任务。"""
        await self.lifecycle_service.on_astrbot_loaded()

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=999)
    async def on_friend_message(self, event: AstrMessageEvent) -> None:
        """私聊消息入口。"""
        await self.event_handlers.on_friend_message(event)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=998)
    async def on_group_message(self, event: AstrMessageEvent) -> None:
        """群聊消息入口。"""
        await self.event_handlers.on_group_message(event)

    @filter.after_message_sent()
    async def on_after_message_sent(self, event: AstrMessageEvent) -> None:
        """消息发送后入口。"""
        await self.event_handlers.on_after_message_sent(event)

    # ==================================================================
    # 指令入口（薄壳：参数转交服务层处理）
    # ==================================================================
    @filter.command("主动消息")
    async def cmd_help(self, event: AstrMessageEvent):
        """显示插件帮助信息。"""
        async for result in self.command_service.handle_help(event):
            yield result

    @filter.command("主动消息状态")
    async def cmd_status(self, event: AstrMessageEvent, scope: str = ""):
        """查询主动消息状态（当前会话 / 全局 / 指定 UMO）。"""
        async for result in self.command_service.handle_status(event, scope):
            yield result

    @filter.command("主动消息发送")
    async def cmd_send(self, event: AstrMessageEvent, scope: str = ""):
        """立即发送主动消息（当前会话 / 全局 / 指定 UMO）。"""
        async for result in self.command_service.handle_send(event, scope):
            yield result

    @filter.command("主动消息开关")
    async def cmd_toggle(
        self,
        event: AstrMessageEvent,
        scope: str = "",
        switch: str = "",
    ):
        """开启或关闭主动消息推送（支持 on/off，缺省为切换）。"""
        async for result in self.command_service.handle_toggle(event, scope, switch):
            yield result

    @filter.command("主动消息重启", alias={"主动消息重载"})
    async def cmd_reload_plugin(self, event: AstrMessageEvent):
        """重载本插件。"""
        async for result in self.command_service.handle_reload_plugin(event):
            yield result

    # priority 高于默认值 0，保证与其他插件注册同名指令时本插件先接管。
    # handler 内部会在回复后调用 stop_event()，后续同名 handler 直接跳过。
    @filter.command(
        "重启AstrBot",
        alias={
            "重启 AstrBot",
            "重启astrbot",
            "重启 astrbot",
            "重载 AstrBot",
            "重载AstrBot",
            "重载 astrbot",
            "重载astrbot",
        },
        priority=100,
    )
    async def cmd_restart_astrbot(self, event: AstrMessageEvent):
        """重启整个 AstrBot 进程。"""
        async for result in self.command_service.handle_restart_astrbot(event):
            yield result

    # ==================================================================
    # 主动消息主流程
    # ==================================================================
    async def check_and_chat(
        self, session_id: str, trigger: TriggerSource = TriggerSource.SCHEDULE
    ) -> None:
        """保留真实触发来源，完成一次完整的主动消息流程。"""
        await self.orchestrator.run(session_id, trigger)
