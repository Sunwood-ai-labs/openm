# OpenM 仕様・実装計画書

> **文書ステータス:** Implemented MVP v0.1 / 開発引き継ぎ用  
> **作成日:** 2026-07-28  
> **対象読者:** プロダクトオーナー、設計者、フロントエンド・バックエンド・インフラ開発者、セキュリティ担当  
> **ベース:** Open WebUI `v0.6.5`（BSD 3-Clause）  
> **推論基盤:** Claude Agent SDK → LiteLLM → Z.AI GLM  
> **実行環境:** ユーザーごとの永続Sandbox、タスクごとのGit worktree

---

## 実装状況（2026-07-29）

MVPとして以下を実装・検証済み。

- `/openm` のコーディングエージェント専用UI
- Project、Task、Event、Permissionの永続化とREST API
- ユーザー単位の永続Sandboxとタスク単位のGit worktree
- Claude Agent SDK実行ランタイム（demo/live切替）
- LiteLLM経由のZ.AI GLMモデル設定
- Bash等のツール実行に対するUI承認フロー
- 停止、再開、再試行API
- Changes、Terminal、Contextインスペクター
- Docker Compose、環境変数テンプレート、ローカル開発スクリプト
- サンドボックス自動テストとChromiumによるE2E確認

実ブラウザでの検証結果と画面証跡は
[openm-validation.md](./openm-validation.md)を参照。

---

## 0. 重要事項

### 0.1 プロジェクト名

本プロジェクトの正式な製品名およびブランド表記を **OpenM** とする。

製品名は大文字の`O`と`M`を使用して`OpenM`と表記する。`OPEN M`、`Open-M`、`OpenManus`は正式表記として使用しない。

推奨する製品説明:

> **OpenM — Your Personal AI Workspace**  
> ユーザー専用Sandbox上で、複数のAIコーディングエージェントへ開発作業を依頼できるWebサービス。

公開前に以下を完了する。

- 商標調査
- GitHub Organization・リポジトリ名の衝突確認
- ドメイン名とSNSアカウントの確認
- `OpenMP`および`OpenM++`など類似名称との誤認可能性の評価
- リポジトリ名、パッケージ名、Container image名の予約

内部コンポーネント、環境変数、画面、文書、リポジトリでは`OpenM`へ統一し、旧称を残さない。

### 0.2 Open WebUIのライセンス境界

- ベースに使用するのは`v0.6.5`タグで固定する。
- `v0.6.5`はBSD 3-Clauseで、商用利用、改造、再配布、UI変更、名称・ロゴ変更が可能。
- 著作権表示、BSD 3-Clause本文、免責条項を保持する。
- Open WebUIまたは作者が本製品を公認・推奨しているような表示をしない。
- `v0.6.6`以降のコードはブランド制限付きライセンスの対象になり得るため、安易にコピーしない。
- 後発版の脆弱性修正を取り込む場合、公開された脆弱性情報をもとに独自実装するか、個別にライセンスを確認する。

### 0.3 Claude Agent SDKとGLM

Claude Agent SDKはClaude Codeのエージェントハーネスをライブラリとして利用する。
実際の推論モデルはLiteLLMを経由してZ.AI GLMへルーティングする。

これは技術的に実現可能だが、AnthropicがGLMとの完全互換を保証する構成ではない。
Anthropic Messages API、Tool Use、ストリーミング、Reasoning、Betaパラメータなどの互換試験を必須とする。

---

## 1. プロダクト概要

OpenMは、ユーザーごとに隔離されたクラウド開発環境を持ち、AIコーディングエージェントへ非同期タスクを依頼できるWebサービスである。

ユーザーはブラウザからリポジトリを選択し、自然言語で開発タスクを依頼する。
エージェントはSandbox内でコードを読み、編集し、コマンドやテストを実行し、差分と成果物を返す。

### 1.1 中心的な価値

- ブラウザだけでコーディングエージェントを利用できる
- ブラウザを閉じてもタスクが継続する
- ユーザーごとにファイル・認証情報・実行環境を隔離する
- 同一ユーザー内では設定、キャッシュ、Skills、成果物を共有できる
- タスクごとにGit worktreeを分離し、複数タスクを安全に並列実行できる
- 変更差分、コマンド、テスト結果、権限要求をUIから確認できる
- LLMをLiteLLM経由で差し替えられる

### 1.2 想定利用者

- 個人開発者
- 小規模開発チーム
- 社内開発組織
- AIによる保守・調査・テストを非同期実行したい利用者

---

## 2. ゴールと非ゴール

### 2.1 MVPゴール

1. ユーザーがログインできる
2. ユーザー専用Sandboxを起動・停止できる
3. Gitリポジトリを登録・cloneできる
4. タスクごとのGit worktreeを作成できる
5. Claude Agent SDKをタスク単位で起動できる
6. LiteLLM経由でGLMを利用できる
7. Agentのテキスト、Tool Use、コマンド、結果をリアルタイム表示できる
8. ファイル変更とGit diffを表示できる
9. タスクを中断できる
10. タスク結果をCommitまたはPatchとして保存できる
11. 危険な操作をUIで許可・拒否できる
12. ユーザーごとの同時実行数、時間、予算を制限できる

### 2.2 MVPの非ゴール

- 完全なIDEの再実装
- VS Code全機能の内蔵
- 任意OSのデスクトップ操作
- 本番環境への自動デプロイ
- 無制限の外部ネットワークアクセス
- Agentによる無確認のGit push
- 複数ユーザーによる同一worktreeの共同編集
- GLM以外の全モデルに対する完全互換保証

### 2.3 将来ゴール

- Pull Request作成・レビュー
- ブラウザ操作
- サブエージェント
- タスクのスケジュール実行
- チーム共有プロジェクト
- 組織ポリシー
- 課金・クォータ
- モデルルーティングとフォールバック
- VS Code Web連携
- 成果物プレビュー

---

## 3. 採用方針

| 項目 | 採用方針 |
|---|---|
| Web UIベース | Open WebUI `v0.6.5` fork |
| フロントエンド | Open WebUI同梱のSvelte UIを改造 |
| 既存バックエンド | 認証・ユーザー・基本会話データを必要範囲で利用 |
| Agent API | Open WebUIとは別のAgent Orchestratorサービス |
| Agent Runtime | Claude Agent SDK |
| LLM Gateway | LiteLLM Proxy |
| 主要モデル | Z.AI GLMのコーディング向けモデル |
| ユーザー隔離 | 1ユーザーにつき1永続Sandbox |
| タスク隔離 | 1タスクにつき1 Git worktree＋1 Agent SDKセッション |
| リアルタイム通信 | 認証付きSSE（250ms間隔のイベント取得、keepalive付き） |
| タスクキュー | Redis系キューまたは同等の永続キュー |
| メタデータDB | PostgreSQLを推奨 |
| 成果物 | S3互換Object Storage |
| Git認証 | ユーザー／プロジェクト単位の短期資格情報 |
| ログ・メトリクス | OpenTelemetry互換 |

---

## 4. システム構成

```text
┌──────────────────────────────────────────────────────┐
│ Browser                                              │
│ Project / Task / Chat / Timeline / Diff / Terminal   │
└──────────────────────────┬───────────────────────────┘
                           │ HTTPS / SSE
┌──────────────────────────▼───────────────────────────┐
│ OpenM Web                                            │
│ Open WebUI v0.6.5 fork                               │
│ Auth / Users / UI / Project Views / Task Views       │
└──────────────────────────┬───────────────────────────┘
                           │ Internal API
┌──────────────────────────▼───────────────────────────┐
│ Agent Orchestrator                                   │
│ Task Queue / Sandbox Lifecycle / Session Mapping     │
│ Permission Requests / Events / Quotas / Audit        │
└───────────────┬──────────────────────┬───────────────┘
                │                      │
       ┌────────▼────────┐    ┌────────▼────────┐
       │ User Sandbox A  │    │ User Sandbox B  │
       │ Task worktrees  │    │ Task worktrees  │
       │ Agent SDK       │    │ Agent SDK       │
       └────────┬────────┘    └────────┬────────┘
                │                      │
                └──────────┬───────────┘
                           │ Anthropic Messages API
                  ┌────────▼────────┐
                  │ LiteLLM Proxy   │
                  │ Auth / Limits   │
                  │ Logging/Route   │
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │ Z.AI GLM        │
                  └─────────────────┘
```

---

## 5. コンポーネント仕様

### 5.1 OpenM Web

責務:

- 認証とセッション
- プロジェクト一覧
- タスク作成・一覧・詳細
- Agentイベントの表示
- Permission要求への応答
- Git diff表示
- ターミナルログ表示
- 成果物の表示・ダウンロード
- Sandbox状態表示
- 利用量表示

OpenM WebはAgent SDKを直接起動しない。
Agent実行権限はAgent Orchestratorだけが持つ。

### 5.2 Agent Orchestrator

責務:

- タスクの受付
- DBへの永続化
- タスクキュー投入
- ユーザーSandboxの割り当て
- Sandbox起動・停止
- Git worktree作成・削除
- Agent Runner起動
- イベントの正規化と配信
- 権限確認
- キャンセルとタイムアウト
- 同時実行数・予算制御
- エラー回復
- 監査ログ

Agent OrchestratorはLLMレスポンス本文を可能な限り解釈せず、SDKイベントを正規化して保存・配信する。

### 5.3 Sandbox Manager

実装候補:

- Coder系環境
- Daytona系環境
- Kubernetes Pod
- Firecracker/microVM
- 専用Container基盤

必要なインターフェース:

```text
create_user_sandbox(user_id, image, resources)
start_sandbox(sandbox_id)
stop_sandbox(sandbox_id)
delete_sandbox(sandbox_id)
exec(sandbox_id, command, cwd, env)
stream_exec(sandbox_id, command, cwd, env)
upload(sandbox_id, source, destination)
download(sandbox_id, source)
snapshot(sandbox_id)
restore(snapshot_id)
health(sandbox_id)
```

### 5.4 Agent Runner

Agent RunnerはユーザーSandbox内で動作する。

責務:

- Claude Agent SDKの起動
- `cwd`の固定
- モデル・予算・最大ターン設定
- Tool Permission処理
- Hook実行
- SDKイベントのOrchestratorへの送信
- Heartbeat
- Cancel受信
- Agent Session ID報告

### 5.5 LiteLLM

責務:

- Anthropic Messages API互換受付
- GLM APIへの変換
- ユーザー／Sandbox別Virtual Key
- レート制限
- 予算制限
- 利用ログ
- モデルルーティング
- リトライ
- 将来のフォールバック

禁止事項:

- LiteLLM管理キーをSandboxへ渡さない
- 全ユーザー共通の無制限キーを配布しない
- `latest`タグだけで本番運用しない

---

## 6. Sandboxとファイル構成

### 6.1 ユーザー単位の永続Sandbox

```text
/workspace/
├── shared/
│   ├── memory/
│   ├── artifacts/
│   ├── uploads/
│   └── skills/
├── projects/
│   └── {project_id}/
│       ├── repository.git/
│       ├── config/
│       └── worktrees/
│           ├── {task_id_1}/
│           └── {task_id_2}/
├── tasks/
│   └── {task_id}/
│       ├── task.json
│       ├── events.jsonl
│       └── outputs/
└── caches/
    ├── npm/
    ├── pip/
    ├── cargo/
    └── tools/
```

### 6.2 タスク分離

- 各タスクは別のAgent SDKセッションを持つ。
- 各タスクは別のGit branchを持つ。
- 各タスクは別のGit worktreeを持つ。
- 同一ユーザーSandbox内のキャッシュは共有できる。
- Agentの書き込み先は原則として対象worktreeとタスク成果物ディレクトリに限定する。
- 会話コンテキストはタスク間で自動共有しない。
- 共有が必要な情報はGit commit、成果物、明示メモリとして受け渡す。

### 6.3 worktree命名

```text
branch: agent/{task_id}-{short_slug}
path:   /workspace/projects/{project_id}/worktrees/{task_id}
```

### 6.4 タスク完了後

選択可能な終了処理:

1. Commitを作成してworktreeを保持
2. Patchを生成してworktreeを削除
3. Pull Requestを作成してworktreeを削除
4. ユーザー確認までworktreeを保持
5. 失敗タスクとして期限付き保持

---

## 7. Agent SDK統合仕様

### 7.1 パッケージ

Python版の第一候補:

```text
claude-agent-sdk
```

必要に応じてTypeScript版も評価する。

### 7.2 セッション方式

- 単発処理には`query()`を利用可能。
- 双方向通信、Permission、Hooks、Custom Toolsを利用するため、基本は`ClaudeSDKClient`を採用する。
- 1タスクにつき1クライアントセッションを生成する。
- Agent Session IDをDBへ保存する。
- Sandbox停止後の再開方式はPoCで検証する。

### 7.3 初期オプション例

```python
options = ClaudeAgentOptions(
    model="claude-glm-code",
    cwd=worktree_path,
    allowed_tools=["Read", "Glob", "Grep"],
    disallowed_tools=[],
    max_turns=40,
    max_budget_usd=5.0,
)
```

実際のTool Policyはユーザー権限、プロジェクトポリシー、タスク種別から生成する。

### 7.4 Tool Policy

| Tool/操作 | 初期ポリシー |
|---|---|
| Read / Glob / Grep | 自動許可 |
| Edit / Write | worktree内のみ自動許可 |
| テスト・lint | allowlistコマンドのみ自動許可 |
| Bash一般 | 確認 |
| パッケージインストール | 確認 |
| 外部ネットワーク | allowlist外は確認 |
| Git commit | 確認またはプロジェクト設定 |
| Git push | 必ず確認 |
| PR作成 | 必ず確認 |
| Sandbox外パス | 拒否 |
| 管理者権限 | 拒否 |
| Docker socket | 提供しない |

### 7.5 Hooks

最低限実装するHook:

- `PreToolUse`: パス、コマンド、ネットワーク、秘密情報を検査
- `PostToolUse`: 実行結果と変更ファイルを監査ログへ記録
- `SessionStart`: タスク情報を記録
- `SessionEnd`: コスト、結果、終了理由を記録
- `Stop`: キャンセル・停止処理

### 7.6 SDKイベントの正規化

| SDKメッセージ | OpenMイベント |
|---|---|
| StreamEvent / text_delta | `agent.text.delta` |
| ToolUseBlock | `agent.tool.requested` |
| ToolResultBlock | `agent.tool.result` |
| Permission要求 | `agent.permission.required` |
| ResultMessage | `agent.message.completed`、`agent.completed` |
| SDK例外 | `agent.failed` |

---

## 8. LiteLLM・GLM仕様

### 8.1 初期構成例

```yaml
model_list:
  - model_name: claude-glm-code
    litellm_params:
      model: zai/glm-4.5-flash
      api_key: os.environ/ZAI_API_KEY
      extra_body:
        thinking:
          type: disabled

  - model_name: claude-glm-main
    litellm_params:
      model: zai/glm-4.5-flash
      api_key: os.environ/ZAI_API_KEY
      extra_body:
        thinking:
          type: disabled

litellm_settings:
  drop_params: true
  redact_user_api_key_info: true
```

v0.1.0では両エイリアスを`zai/glm-4.5-flash`へ固定する。別モデルへ切り替える
場合は、Z.AI契約、提供リージョン、モデル一覧を確認して
`config/litellm.yaml`を変更する。

### 8.2 Agent Runner環境変数

```text
ANTHROPIC_BASE_URL=http://litellm:4000/v1
ANTHROPIC_AUTH_TOKEN=<OPENM_LITELLM_TOKEN>
ANTHROPIC_DEFAULT_SONNET_MODEL=claude-glm-code
ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-glm-main
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1
```

### 8.3 必須互換試験

- `/v1/messages`通常応答
- ストリーミング
- Tool Use
- Tool Result
- 複数Tool Call
- 長いTool定義
- 大きいJSON引数
- Reasoningブロック
- 長文コンテキスト
- サブエージェント
- セッション継続
- Token Count
- 未対応パラメータ除去
- エラー形式の変換
- Rate limit時の挙動
- Cancel時の挙動

### 8.4 LiteLLMバージョン管理

- バージョンとContainer digestを固定する。
- 自動更新しない。
- Stagingで互換テスト後に更新する。
- 既知の侵害バージョン`1.82.7`と`1.82.8`は使用禁止。
- 依存パッケージのSBOMを生成する。
- Virtual KeyはユーザーまたはSandbox単位で発行する。

---

## 9. タスクライフサイクル

### 9.1 状態

```text
draft
queued
preparing
running
waiting_permission
waiting_user
cancelling
cancelled
succeeded
failed
timed_out
archived
```

### 9.2 状態遷移

```text
draft
  ↓ submit
queued
  ↓ worker acquired
preparing
  ↓ sandbox/worktree ready
running
  ├─ permission needed → waiting_permission → running
  ├─ user input needed → waiting_user → running
  ├─ cancel requested → cancelling → cancelled
  ├─ timeout → timed_out
  ├─ error → failed
  └─ complete → succeeded
```

### 9.3 冪等性

- タスク作成APIはIdempotency-Keyを受け付ける。
- worktree作成は既存有無を確認する。
- Runner起動は同一タスクにつき1個に制限する。
- イベントは単調増加のsequence番号を持つ。
- 再接続時は最後に受信したsequence以降を再送する。

---

## 10. API仕様（案）

### 10.1 Projects

```text
GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}
DELETE /api/v1/projects/{project_id}
POST   /api/v1/projects/{project_id}/sync
```

### 10.2 Tasks

```text
GET    /api/v1/tasks
POST   /api/v1/tasks
GET    /api/v1/tasks/{task_id}
POST   /api/v1/tasks/{task_id}/cancel
POST   /api/v1/tasks/{task_id}/resume
POST   /api/v1/tasks/{task_id}/retry
POST   /api/v1/tasks/{task_id}/archive
```

### 10.3 Permission

```text
POST /api/v1/tasks/{task_id}/permissions/{request_id}
```

Request:

```json
{
  "decision": "allow_once",
  "reason": "User approved package installation"
}
```

Decision:

```text
allow_once
allow_for_task
deny
```

危険操作に対するグローバルな`always_allow`はMVPでは提供しない。

### 10.4 Files and Git

```text
GET  /api/v1/tasks/{task_id}/files
GET  /api/v1/tasks/{task_id}/files/content
GET  /api/v1/tasks/{task_id}/diff
GET  /api/v1/tasks/{task_id}/commits
POST /api/v1/tasks/{task_id}/commit
POST /api/v1/tasks/{task_id}/push
POST /api/v1/tasks/{task_id}/pull-request
```

### 10.5 Sandbox

```text
GET  /api/v1/sandbox
POST /api/v1/sandbox/start
POST /api/v1/sandbox/stop
GET  /api/v1/sandbox/usage
```

### 10.6 Server-Sent Events

```text
GET /api/v1/openm/tasks/{task_id}/events/stream?after={sequence}
```

Bearer認証済みユーザーが所有するタスクだけを購読できる。サーバーは新しいイベントを
250ms間隔で確認し、SSEの`message`イベントとして送信する。完了状態へ到達すると
`done`イベントを送り、アイドル中は接続維持用コメントを送る。

共通Envelope:

```json
{
  "event_id": "evt_...",
  "task_id": "task_...",
  "sequence": 123,
  "timestamp": "2026-07-28T12:34:56Z",
  "type": "agent.tool.requested",
  "data": {}
}
```

イベント種別:

```text
task.status.changed
sandbox.status.changed
agent.text.delta
agent.message.completed
agent.tool.requested
agent.tool.running
agent.tool.result
agent.permission.required
agent.file.changed
agent.diff.updated
agent.terminal.output
agent.usage.updated
agent.completed
agent.failed
agent.cancelled
```

---

## 11. データモデル

### 11.1 User

```text
id
email
display_name
role
status
created_at
updated_at
```

### 11.2 Sandbox

```text
id
user_id
provider
provider_sandbox_id
status
image_version
cpu_limit
memory_limit
disk_limit
last_active_at
created_at
updated_at
```

### 11.3 Project

```text
id
user_id
name
repository_url
default_branch
sandbox_id
credential_reference
settings_json
created_at
updated_at
```

### 11.4 Task

```text
id
user_id
project_id
sandbox_id
parent_task_id
title
prompt
status
branch_name
worktree_path
agent_session_id
model
max_turns
max_budget
actual_cost
started_at
completed_at
created_at
updated_at
```

### 11.5 TaskEvent

```text
id
task_id
sequence
event_type
payload_json
created_at
```

### 11.6 PermissionRequest

```text
id
task_id
tool_use_id
tool_name
tool_input_json
risk_level
status
decision
decided_by
decided_at
created_at
```

### 11.7 Artifact

```text
id
task_id
name
media_type
storage_key
size_bytes
sha256
created_at
```

---

## 12. UI仕様

### 12.1 グローバルナビゲーション

- Dashboard
- Projects
- Tasks
- Artifacts
- Usage
- Settings
- Sandbox status

### 12.2 Dashboard

表示:

- 実行中タスク
- 許可待ちタスク
- 最近完了したタスク
- Sandbox状態
- 今月の利用量
- 最近のプロジェクト

### 12.3 Project画面

- リポジトリ情報
- branch一覧
- タスク一覧
- 新規タスク
- project memory
- Skills/MCP設定
- Git認証状態
- Sandbox環境情報

### 12.4 Task画面

推奨3ペイン:

```text
┌──────────────┬────────────────────────┬──────────────────┐
│ Files        │ Chat / Activity        │ Diff / Terminal  │
│ Project tree │ Agent timeline         │ Preview          │
└──────────────┴────────────────────────┴──────────────────┘
```

主要要素:

- タスクタイトル・状態
- Agent応答
- Tool Callカード
- Permissionカード
- コマンド出力
- 変更ファイル一覧
- Diffビュー
- テスト結果
- 成果物
- Cancel
- Resume
- Commit
- Push
- Pull Request

### 12.5 Tool Callカード

表示:

- Tool名
- 開始・終了時間
- 入力概要
- 実行対象
- リスクレベル
- 出力概要
- Exit code
- 折りたたみ式全文

### 12.6 Permissionダイアログ

表示:

- 実行しようとしている操作
- コマンドまたは変更内容
- 対象ファイル・URL
- リスク説明
- `1回だけ許可`
- `このタスク中は許可`
- `拒否`

### 12.7 レスポンシブ対応

- Desktopを第一優先
- Tabletは2ペイン
- Mobileはタブ切り替え
- ターミナルとDiffの同時表示はDesktop限定でもよい

---

## 13. セキュリティ要件

### 13.1 分離

- ユーザーごとにSandboxを分離する。
- 異なるユーザーの永続Volumeを共有しない。
- SandboxからHost filesystemをmountしない。
- Docker socketを渡さない。
- Agent Orchestratorの管理資格情報をSandboxへ渡さない。
- Sandbox用資格情報は短期・限定スコープにする。

### 13.2 ネットワーク

- デフォルトdenyまたは宛先allowlistを推奨。
- LiteLLM、Git provider、Package registryなど必要宛先のみ許可する。
- metadata endpoint、内部管理API、他Sandboxネットワークを遮断する。
- DNSログと外向き通信ログを保持する。

### 13.3 シークレット

- DBへ平文保存しない。
- Secret managerの参照IDだけをDBへ保存する。
- タスクログへ環境変数を出力しない。
- Agent出力を保存する前にsecret redactionを行う。
- Git資格情報はプロジェクト単位でスコープする。

### 13.4 コマンド制御

明示拒否例:

```text
sudo
mount
nsenter
docker socket access
host network access
credential file dump
recursive deletion outside worktree
shell history dump
process environment dump
```

文字列マッチだけをセキュリティ境界にしない。
Sandboxそのものの権限、mount、network policy、OS userで強制する。

### 13.5 Open WebUI旧版対策

`v0.6.5`は公式サポート対象外であり、既知脆弱性を含み得る。

必須対応:

- インターネットへ直接公開せず、Reverse Proxy/WAFを置く
- CSP、CSRF、Cookie、Session設定を再監査
- HTML/Markdownレンダリングをサニタイズ
- UploadのMIME・拡張子・サイズを検査
- 認可を全APIで再確認
- npm/Python依存関係を更新・監査
- SAST/DAST/SCAをCIへ導入
- 独立したPenetration Testを実施

---

## 14. 可用性・性能

### 14.1 初期SLO案

| 指標 | MVP目標 |
|---|---|
| Web API可用性 | 99.5% |
| タスク受付P95 | 500ms以下 |
| Event配信遅延P95 | 2秒以下 |
| 既存Sandbox再開 | 30秒以下 |
| 新規Sandbox作成 | 120秒以下 |
| Cancel反映 | 10秒以下 |
| イベント欠損 | 0件 |

### 14.2 制限

初期値:

- ユーザー同時タスク: 2
- タスク最大時間: 60分
- タスク最大ターン: 40
- タスク最大予算: 管理者設定
- Sandbox idle停止: 30分
- worktree保持: 完了後7日
- ログ保持: 30日

---

## 15. 監視・監査

### 15.1 メトリクス

- タスク数と状態
- Queue待ち時間
- Sandbox起動時間
- Agent実行時間
- Tool別実行回数・失敗率
- Permission許可・拒否数
- LLM token・cost
- LiteLLMエラー率
- GLMレスポンス時間
- WebSocket接続数
- CPU・メモリ・ディスク

### 15.2 ログ

- 認証ログ
- Sandbox lifecycle
- Task lifecycle
- Tool Use
- Permission decision
- Git操作
- 管理者操作
- LiteLLM request ID

ログへPromptやファイル内容を保存するかは、プライバシーポリシーと設定に従う。

### 15.3 トレース

共通Correlation ID:

```text
request_id
user_id
task_id
sandbox_id
agent_session_id
litellm_request_id
```

---

## 16. テスト計画

### 16.1 Unit

- 状態遷移
- Permission policy
- パス検証
- イベント変換
- Git branch/worktree命名
- Quota計算
- Secret redaction

### 16.2 Integration

- OpenM Web → Orchestrator
- Orchestrator → Sandbox
- Sandbox → Agent SDK
- Agent SDK → LiteLLM
- LiteLLM → GLM
- Permission round trip
- Cancel
- Resume
- Git diff/commit

### 16.3 GLM Agent評価

固定タスクセットを用意する。

1. 1ファイルのバグ修正
2. 複数ファイルの機能追加
3. テスト失敗の原因調査
4. 依存関係更新
5. リファクタリング
6. ドキュメント生成
7. 不明瞭な指示に対する質問
8. 危険コマンドの拒否
9. 長時間コマンドの監視
10. Tool Call JSONの連続実行

評価指標:

- タスク成功率
- テスト合格率
- Tool Callエラー率
- 不要変更数
- 危険操作数
- 平均ターン数
- 平均コスト
- P50/P95完了時間

### 16.4 Security

- IDOR
- 権限昇格
- 他ユーザーSandboxアクセス
- Path traversal
- Command injection
- Prompt injection
- Stored XSS
- SSRF
- Secret exfiltration
- Malicious repository
- Malicious package scripts

---

## 17. CI/CD

### 17.1 必須ジョブ

- Format/Lint
- Unit tests
- Integration tests
- Type check
- Dependency audit
- Secret scan
- Container scan
- SBOM generation
- License scan
- Migration test
- GLM smoke test

### 17.2 Release

- Semantic Versioningを採用
- Open WebUIベースのfork commitを記録
- Agent SDK、Claude Code binary、LiteLLM、GLMモデルをversion pin
- Stagingで固定評価セットを実行
- Container digestを本番マニフェストへ記録
- DB migrationのrollback手順を用意

---

## 18. 実装ロードマップ

### Phase 0: 技術検証

期間目安: 1〜2週間

成果物:

- Agent SDK → LiteLLM → GLMの接続
- Read/Edit/Bashによるサンプル修正
- SDKイベントのJSON保存
- Permission Hook
- GLM互換性レポート

完了条件:

- 10種類の固定タスクで基本動作
- Tool Useが安定して往復
- ストリーミングが機能
- 危険コマンドを拒否可能

### Phase 1: 基盤

期間目安: 2〜4週間

成果物:

- Open WebUI `v0.6.5` fork
- Orchestrator
- DB schema
- User Sandbox lifecycle
- Project登録
- Git clone/worktree
- Task queue
- Event WebSocket

完了条件:

- 2ユーザーを別Sandboxで実行
- 同一ユーザーで2タスク並列実行
- 他ユーザーのファイルへアクセス不能

### Phase 2: コーディングUI

期間目安: 3〜5週間

成果物:

- Dashboard
- Project画面
- Task画面
- Agent timeline
- Tool cards
- Permission UI
- File tree
- Diff
- Terminal logs
- Cancel

完了条件:

- ブラウザだけでタスク作成からDiff確認まで完了
- 再接続後もイベントが欠損しない

### Phase 3: Git・成果物

期間目安: 2〜3週間

成果物:

- Commit
- Push承認
- PR作成
- Artifact保存
- Task派生
- Branch継承

完了条件:

- タスク結果からPRを安全に作成
- Git資格情報がユーザー間で分離

### Phase 4: Hardening

期間目安: 3〜6週間

成果物:

- 旧Open WebUIコードのセキュリティ監査
- CSP/CSRF/XSS対策
- Network policy
- Secret manager
- Rate limit
- Quota
- Audit log
- SAST/DAST/SCA
- Penetration test

完了条件:

- Critical/Highの未対応事項がない
- Sandbox escapeテスト合格
- マルチテナント認可テスト合格

### Phase 5: Beta

成果物:

- 利用規約
- プライバシーポリシー
- OSS Notices
- 運用Runbook
- 障害対応
- バックアップ・復元
- Usage/Cost画面

---

## 19. MVP受け入れ基準

- [ ] ユーザーAからユーザーBのSandboxへアクセスできない
- [ ] 同一ユーザーが2タスクを並列実行できる
- [ ] タスクごとに別worktreeが作成される
- [ ] AgentがGLMを使ってコードを変更できる
- [ ] Tool Useがリアルタイム表示される
- [ ] コマンド出力がリアルタイム表示される
- [ ] worktree外への書き込みを拒否できる
- [ ] 危険操作がPermission待ちになる
- [ ] ユーザーが許可・拒否できる
- [ ] タスクをCancelできる
- [ ] WebSocket再接続でイベントを復元できる
- [ ] Git diffをUI表示できる
- [ ] CommitまたはPatchを作成できる
- [ ] 使用量と予算を記録できる
- [ ] セキュリティ監査ログを取得できる
- [ ] BSD 3-Clause表示を製品内に掲載している

---

## 20. 主なリスク

| リスク | 影響 | 対策 |
|---|---|---|
| OpenM類似名称との混同 | 検索性・商標・誤認問題 | 商標調査、ロゴ差別化、製品説明の併記 |
| Open WebUI旧版の脆弱性 | 侵害 | 独自監査・独自修正・WAF |
| 後発コードのライセンス混入 | BSD維持不能 | コード由来を記録、コピー禁止 |
| GLMのAgent SDK互換不足 | タスク失敗 | 固定評価、Gateway adapter、fallback |
| LiteLLM更新による破壊 | 障害 | pin、Staging、回帰テスト |
| Agentの危険操作 | データ損失 | Sandbox、Policy、Permission |
| タスク間のファイル干渉 | 変更競合 | Git worktree |
| Sandboxコスト | 採算悪化 | idle停止、Quota、キャッシュ |
| 長期セッション復元失敗 | UX低下 | 外部イベント保存、Git checkpoint |
| Prompt injection | 情報漏洩 | Egress制御、Secret分離、Tool制限 |

---

## 21. 未決事項

- [ ] OpenMの商標・ドメイン・主要SNSアカウント調査
- [ ] Sandbox providerの確定
- [ ] Python SDKかTypeScript SDKか
- [ ] GLMの正式モデル・契約プラン
- [ ] Claudeモデルのfallbackを用意するか
- [ ] Open WebUIのDBを継続利用するか、独自DBへ移行するか
- [ ] 認証をOpen WebUIから独立させるか
- [ ] GitHub Appを使用するか、個人トークンを使用するか
- [ ] チーム共有Sandboxを将来提供するか
- [ ] Sandbox永続Volumeの暗号化方式
- [ ] 会話・コード・ログの保持期間
- [ ] 課金方式

---

## 22. 開発引き継ぎチェックリスト

最初に担当者が行うこと:

1. Open WebUI `v0.6.5`タグをforkする
2. LICENSEとNOTICEの配置を確認する
3. ベースcommit SHAを記録する
4. Agent SDKの最小PoCを作成する
5. LiteLLMを安全な固定バージョンで起動する
6. GLMモデルを登録する
7. `Read → Edit → Bash test`を検証する
8. ToolイベントのサンプルJSONを保存する
9. Sandbox providerでユーザー隔離を検証する
10. Git worktreeによる並列タスクを検証する
11. API/OpenAPI schemaを確定する
12. UI wireframeをレビューする
13. Threat modelを作成する
14. Phase 0の合否を判断する

---

## 23. 参照資料

- Open WebUI `v0.6.5` LICENSE  
  https://raw.githubusercontent.com/open-webui/open-webui/v0.6.5/LICENSE
- Open WebUI License History  
  https://github.com/open-webui/open-webui/blob/main/LICENSE_HISTORY
- Open WebUI License説明  
  https://docs.openwebui.com/license/
- Claude Agent SDK  
  https://code.claude.com/docs/en/agent-sdk/overview
- Claude Agent SDK Python  
  https://github.com/anthropics/claude-agent-sdk-python
- Claude Code LLM Gateway  
  https://code.claude.com/docs/en/llm-gateway
- Claude Code Model Configuration  
  https://code.claude.com/docs/en/model-config
- LiteLLM  
  https://docs.litellm.ai/
- OpenMP Trademark Guidelines  
  https://www.openmp.org/about/trademarks/
- OpenM++  
  https://openmpp.org/

---

## 24. 推奨する次の作業

最優先はUI実装ではなく、以下の縦切りPoCである。

```text
ブラウザからタスク入力
  ↓
OrchestratorがユーザーSandboxを選択
  ↓
Git worktree作成
  ↓
Agent SDK起動
  ↓
LiteLLM経由でGLM実行
  ↓
Read/Edit/Bash
  ↓
イベントをWebSocket表示
  ↓
Git diff表示
  ↓
Commit
```

この一連が安定して動いた後に、Open WebUIの画面を本格的なコーディングエージェントUIへ置き換える。
