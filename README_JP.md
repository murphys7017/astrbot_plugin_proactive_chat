# プロアクティブメッセージ（Personal Runtime 版）

> **互換性**：これは本プロジェクトの `murphys7017/AstrBot` 向けに調整した版です。Personal Runtime、Runtime Observation Sensor、Dashboard プラグインビュー API に依存します。その他の AstrBot バージョン、公式標準版、またはこれらの API を含まないブランチでは動作しない場合があります。

この AstrBot プラグインは、プロアクティブな「機会」をスケジュールします。プラグイン自身は LLM を呼び出さず、Prompt や人格を組み立てず、プラットフォームへ直接送信しません。

```text
スケジューラ
  -> Runtime Observation Sensor
  -> AstrBot Personal Runtime / Observation Inbox
  -> Personal Policy
  -> Personal Expression
  -> AstrBot Output Controller / プラットフォームアダプタ
```

通常の会話とプロアクティブな機会は、同じ人格、クールダウン、静音時間、予算、出力制御、配信経路を共有します。プラグインは構造化された短い事実だけを送信し、発話するかどうかと最終的な文面は Personal Runtime が決定します。

## 現在のバージョン

- プラグイン：`v1.3.0-beta.2`
- 必要な AstrBot：`4.29.0-beta.1` 以上
- リポジトリ：[murphys7017/astrbot_plugin_proactive_chat](https://github.com/murphys7017/astrbot_plugin_proactive_chat)

現在のブランチでは、プラグイン独自の LLM、Prompt、TTS、分割送信、通知、テレメトリ、独立 Web サーバーを削除しました。管理画面は AstrBot Dashboard のプラグインビューを利用します。

## インストールと設定

AstrBot のプラグイン管理画面からインストールするか、`data/plugins/astrbot_plugin_proactive_chat` に配置してください。設定では対象のプライベートチャット・グループチャットの UMO を選択します。

設定スキーマに残っているのはスケジュールとセッション関連の項目だけです。

- `friend_settings`
- `group_settings`
- `auto_trigger_settings`
- `schedule_settings`
- `group_idle_trigger_minutes`

人格、モデル、Prompt、TTS、出力形式は AstrBot Personal Runtime 側で管理します。`主动消息发送` コマンドもスケジュール事実だけを送信します。

## Runtime Observation 契約

プラグインが登録する識別子：

- plugin id：`astrbot_plugin_proactive_chat`
- source id：`scheduled_proactive_message`
- observation kind：`proactive_schedule_due`

Payload は `trigger` や `session_type` のような短いスカラー事実だけを含みます。ユーザー本文、Prompt、最終返信、ツール引数は含みません。事実の有効期限は 180 秒で、`schedule_due` キーで重複をまとめます。

Personal Runtime は、ソース許可、対象能力、有効期限、クールダウン、静音時間、日次予算、Policy の判断（`ignore`、`observe`、`defer`、`express`）を引き続き適用します。

## Dashboard とコマンド

Dashboard のプラグインビューでは、セッション、有効な設定、APScheduler タスク、グループチャットの沈黙タイマー、アイドルトリガーを確認できます。即時トリガー、再スケジュール、キャンセルも可能ですが、Personal Runtime を迂回することはありません。

主なコマンド：

| コマンド | 役割 |
| --- | --- |
| `主动消息` | ヘルプ表示 |
| `主动消息状态` | 現在または全体の状態表示 |
| `主动消息发送` | プロアクティブ機会を送信 |
| `主动消息开关 on/off` | 現在のセッションを切り替え |
| `主动消息重启` | プラグインを再ロード |

## 失敗時の動作

事実が有効期限切れ、またはプラットフォームの一時的な利用不可で拒否された場合、プラグインは理由を記録して後で再スケジュールします。終端的な拒否、無効化されたセッション、利用できないセンサー API では現在のタスクを消去し、無限に再試行しません。直接送信へのフォールバックはありません。

## 開発チェック

```powershell
python -m compileall -q main.py core
python -c "import json; json.load(open('_conf_schema.json', encoding='utf-8'))"
git diff --check
```

## ライセンス

GNU Affero General Public License v3.0。詳細は [LICENSE](LICENSE) を参照してください。
