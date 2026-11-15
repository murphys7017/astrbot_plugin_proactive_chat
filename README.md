# 主动消息（Personal Runtime 版）

> **兼容性要求**：这是为本项目 `murphys7017/AstrBot` 定制的插件版本，依赖其中的 Personal Runtime、Runtime Observation Sensor 和 Dashboard 插件视图接口。其他 AstrBot 版本、官方标准发行版或未包含这些接口的分支可能不兼容；请以本项目配套版本为准。

这是一个 AstrBot 主动调度插件。它负责决定“什么时候提交一次主动机会事实”，不负责生成文案，也不直接调用模型或向平台发送消息。

主动输出的唯一链路是：

```text
插件调度器
  -> Runtime Observation Sensor
  -> AstrBot Personal Runtime / Observation Inbox
  -> Personal Policy 判断是否表达
  -> Personal Expression 按人格生成回复
  -> AstrBot Output Controller / 平台适配器投递
```

这样主动消息和普通对话共享同一套人格、冷却、安静时段、每日预算、输出控制和平台投递逻辑。插件只提交结构化事实，最终是否说话以及说什么由 Personal Runtime 决定。

## 当前版本

- 插件版本：`v1.3.0-beta.2`
- 最低 AstrBot 版本：`4.29.0-beta.1`
- 仓库：[murphys7017/astrbot_plugin_proactive_chat](https://github.com/murphys7017/astrbot_plugin_proactive_chat)

当前分支已经移除旧的独立 LLM、Prompt、TTS、分段发送、通知中心、遥测和独立 Web 管理服务器。管理页面使用 AstrBot Dashboard 的插件视图，主动表达使用宿主 Personal Runtime。

## 安装

在 AstrBot 插件管理器中安装本仓库，或把插件目录放到 `data/plugins/astrbot_plugin_proactive_chat`。安装后在插件配置中选择需要启用的私聊或群聊会话。

插件需要宿主提供 Runtime Observation Sensor API。旧版 AstrBot 没有这个能力时，插件会保留调度状态，但不会绕过 Personal Runtime 直接发送消息。

## 配置

配置由 `_conf_schema.json` 驱动，只有调度和会话选择相关字段。

### 私聊设置

```json
{
  "enable": true,
  "session_list": ["platform:FriendMessage:user_id"],
  "auto_trigger_settings": {
    "enable_auto_trigger": false,
    "auto_trigger_after_minutes": 5
  },
  "schedule_settings": {
    "min_interval_minutes": 30,
    "max_interval_minutes": 600,
    "enable_quiet_hours": true,
    "quiet_hours": "1-7"
  }
}
```

### 群聊设置

群聊配置与私聊类似，另外有 `group_idle_trigger_minutes`，用于群聊沉默后重新建立调度机会。

`auto_trigger_settings` 只负责在配置的空闲窗口提交主动事实。它不会让插件直接发消息，Personal Policy 可以选择 `ignore`、`observe`、`defer` 或 `express`。

### 会话覆写

插件保留每个会话的轻量覆写文件，只允许覆写以下调度字段：

- `enable`
- `session_name`
- `auto_trigger_settings`
- `schedule_settings`
- `group_idle_trigger_minutes`

人格、模型、Prompt、TTS 和输出格式不在插件中配置，统一由 AstrBot 和 Personal Runtime 管理。

## Dashboard 页面

插件会注册一个 AstrBot Dashboard 插件页面，用于查看和操作调度状态。页面通过宿主插件视图 API 读取以下信息：

- 当前插件状态
- 已知会话和生效配置
- APScheduler 任务及下一次触发时间
- 群聊沉默计时器
- 自动触发状态
- 立即触发、重新排期、取消任务

页面操作只影响插件调度器，不会绕过 Personal Runtime。

## 指令

插件仍提供以下管理指令：

| 指令 | 作用 |
| --- | --- |
| `主动消息` | 显示帮助 |
| `主动消息状态` | 查看当前会话状态 |
| `主动消息状态 全局` | 查看全局状态 |
| `主动消息发送` | 提交一次手动主动机会 |
| `主动消息开关 on/off` | 修改当前会话开关 |
| `主动消息重启` | 重载插件 |

`主动消息发送` 只提交 `proactive_schedule_due` 事实，不会生成固定台词。

## Runtime Observation 契约

插件注册的传感器标识为：

- plugin id：`astrbot_plugin_proactive_chat`
- source id：`scheduled_proactive_message`
- observation kind：`proactive_schedule_due`

提交载荷只包含短小的结构化事实：

```json
{
  "trigger": "schedule",
  "session_type": "friend"
}
```

它不包含用户原文、Prompt、最终回复或工具参数。事实进入 Personal Runtime 后会经过来源权限、会话能力、过期时间、合并、冷却、安静时段和预算检查。

主动事实默认有效期为 180 秒，并使用 `schedule_due` 合并键，避免重复点击或重复调度在同一会话堆积多个评估。

## 失败和重排期

- Personal Runtime 接纳事实后，私聊继续安排下一次调度，群聊清理当前调度状态并等待下一次群聊沉默流程。
- Personal Runtime 未接纳事实或传感器不可用时，插件会记录警告并重新排期，不会直接发送备用文本。
- 插件终止期间不会提交新的事实。
- 平台不支持主动消息或 Personal Runtime 时，事实会被拒绝并重新排期。

这保证了插件失败时不会出现“插件自己发一条、Personal 又发一条”的双重输出。

## 目录结构

```text
main.py                         插件装配和 AstrBot 事件入口
core/adapters/                  AstrBot 平台、事件和会话适配
core/commands/                  管理指令
core/domain/                    触发来源和会话键等轻量领域类型
core/services/config_service.py 配置校验与会话生效配置
core/services/scheduler_service.py APScheduler 和临时计时器
core/services/personal_runtime_bridge.py Runtime Observation 适配
core/services/proactive_orchestrator.py 调度事实提交与失败重排
core/services/plugin_view_service.py Dashboard 插件页面 API
core/services/state_builder.py  Dashboard 状态投影
core/store/                    会话数据和覆写持久化
views/proactive/               AstrBot Dashboard 插件视图
```

## 从旧版本升级

旧版本中的以下能力已经移除：

- 插件自己的 LLM Provider 调用
- 插件自己的主动 Prompt 和人格选择
- 插件自己的 TTS 与分段发送
- 独立 FastAPI/uvicorn Web 管理端
- 通知中心
- 匿名遥测

旧配置中的这些字段不会再参与运行。请把模型、人格、TTS、输出节奏和预算迁移到 AstrBot 的 Personal Runtime 配置；插件只保留会话列表和调度设置。

旧版 `session_data.json` 会继续用于恢复调度时间和会话状态。升级后如果会话键格式不完整，插件会在初始化阶段尝试规范化；无法解析的记录会被跳过并写入日志。

## 排查

### 插件有任务但没有消息

这是正常的可能结果：调度器只提交机会事实，Personal Policy 可能因为冷却、安静时段、预算、重复风险或缺乏自然表达价值而保持安静。请同时查看 AstrBot Personal Runtime 日志。

### 日志提示 Runtime Observation Sensor 不可用

说明当前 AstrBot 版本没有提供插件传感器 API，或者插件上下文尚未完成初始化。升级到 `4.29.0-beta.1` 或更高版本，并确认插件已启用。

### 任务不断重新排期

重点检查：

1. 平台是否支持主动消息和 Personal Runtime。
2. 会话 UMO 是否与平台实际会话一致。
3. 对应私聊或群聊设置是否启用。
4. Personal Runtime 是否被静音、处于安静时段或达到每日预算。
5. 是否存在插件重载或宿主重启导致的短暂初始化窗口。

## 开发

开发时保持 `main.py` 只负责装配和事件入口。主动逻辑放在 `core/services`，不要在插件中调用 Provider、构造 Prompt 或直接调用平台发送 API。

常用静态检查：

```powershell
python -m compileall -q main.py core
python -c "import json; json.load(open('_conf_schema.json', encoding='utf-8'))"
git diff --check
```

## 许可证

GNU Affero General Public License v3.0，详见 [LICENSE](LICENSE)。
