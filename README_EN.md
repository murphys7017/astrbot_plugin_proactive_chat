# Proactive Chat (Personal Runtime edition)

> **Compatibility**: This is a project-specific build for `murphys7017/AstrBot`. It depends on that project's Personal Runtime, Runtime Observation Sensor, and Dashboard plugin-view APIs. Other AstrBot versions, the standard upstream distribution, or branches without these APIs may be incompatible.

This AstrBot plugin schedules proactive opportunities. It does not call an LLM, build prompts, render a persona, or send platform messages by itself.

```text
Scheduler
  -> Runtime Observation Sensor
  -> AstrBot Personal Runtime / Observation Inbox
  -> Personal Policy
  -> Personal Expression
  -> AstrBot Output Controller / platform adapter
```

The same Persona, cooldown, quiet-hour, budget, output, and delivery path is used for ordinary conversations and proactive opportunities. The plugin submits a small structured fact; Personal Runtime decides whether to speak and produces the final reply.

## Current version

- Plugin: `v1.3.0-beta.2`
- Minimum AstrBot: `4.29.0-beta.1`
- Repository: [murphys7017/astrbot_plugin_proactive_chat](https://github.com/murphys7017/astrbot_plugin_proactive_chat)

The current branch removes the plugin-owned LLM, prompt, TTS, segmented delivery, notification, telemetry, and standalone web-server layers. The management page is an AstrBot Dashboard plugin view.

## Installation and configuration

Install the repository from the AstrBot plugin manager or place it in `data/plugins/astrbot_plugin_proactive_chat`. Select the private or group UMO values to manage.

The schema contains only scheduling and session settings:

- `friend_settings`
- `group_settings`
- `auto_trigger_settings`
- `schedule_settings`
- `group_idle_trigger_minutes`

Persona, model, prompt, TTS, and output formatting are configured by AstrBot Personal Runtime. A manual `主动消息发送` command also submits only a scheduling fact.

## Runtime Observation contract

The plugin registers:

- plugin id: `astrbot_plugin_proactive_chat`
- source id: `scheduled_proactive_message`
- observation kind: `proactive_schedule_due`

The payload contains only short scalar facts such as `trigger` and `session_type`. It never contains user text, prompts, final reply material, or tool arguments. Facts expire after 180 seconds and coalesce under `schedule_due`.

Personal Runtime still applies source admission, target capability, expiry, cooldown, quiet hours, daily budgets, and the policy decision (`ignore`, `observe`, `defer`, or `express`).

## Dashboard and commands

The Dashboard plugin view shows sessions, effective configuration, APScheduler jobs, group idle timers, and auto-trigger state. It supports immediate trigger, reschedule, and cancellation without bypassing Personal Runtime.

Available commands:

| Command | Purpose |
| --- | --- |
| `主动消息` | Show help |
| `主动消息状态` | Show current or global state |
| `主动消息发送` | Submit a proactive opportunity |
| `主动消息开关 on/off` | Change the current session switch |
| `主动消息重启` | Reload the plugin |

## Failure behavior

If Personal Runtime does not admit a fact, the plugin records a warning and schedules the next attempt. It never falls back to a direct message. Unsupported platforms and unavailable sensor APIs follow the same safe path.

## Project layout

```text
main.py
core/adapters/
core/commands/
core/domain/
core/services/config_service.py
core/services/scheduler_service.py
core/services/personal_runtime_bridge.py
core/services/proactive_orchestrator.py
core/services/plugin_view_service.py
core/services/state_builder.py
core/store/
views/proactive/
```

## Development checks

```powershell
python -m compileall -q main.py core
python -c "import json; json.load(open('_conf_schema.json', encoding='utf-8'))"
git diff --check
```

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
