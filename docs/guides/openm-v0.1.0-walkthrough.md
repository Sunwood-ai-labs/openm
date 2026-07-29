# OpenM v0.1.0 導入ウォークスルー

OpenMは、ブラウザからコーディングタスクを依頼し、Claude Agent SDKの作業と
Git差分を一つの会話画面で追跡するセルフホスト型Workspaceです。このガイドでは
GLMを使う最小構成を起動し、最初のファイル作成を確認します。

## 1. 必要なもの

- Docker DesktopまたはDocker Engine + Compose
- Git
- Z.AI APIキー
- OpenMを開くブラウザ

## 2. 環境ファイルを作る

```powershell
git clone https://github.com/Sunwood-ai-labs/openm.git
Set-Location openm
Copy-Item .env.openm.example .env.openm
```

`.env.openm`の`ZAI_API_KEY`を実際のキーへ置き換えます。必要に応じて
`LITELLM_MASTER_KEY`も変更してください。ブラウザへ公開するポートを変える場合は
次の設定を追加します。

```dotenv
OPENM_HOST_PORT=3001
```

## 3. OpenMとLiteLLMを起動する

```powershell
docker compose --env-file .env.openm -f docker-compose.openm.yaml up --build
```

既定構成ではOpenMが`http://localhost:3000`、LiteLLMがCompose内部の
`http://litellm:4000`で動作します。LiteLLMの`claude-glm-code`と
`claude-glm-main`は、v0.1.0では`zai/glm-4.5-flash`へ接続されます。

## 4. 最初のWorkspaceを作る

1. OpenMへサインインします。
2. `/openm`を開きます。
3. 新しいWorkspaceを作成し、対象Gitリポジトリとbranchを登録します。
4. チャット入力欄へタスクを送信します。

最初の確認には、次のような依頼が適しています。

```text
Writeツールで docs/openm-demo.md を作成してください。
見出し、箇条書き、検証結果をMarkdownで記載し、
作成後にReadツールで内容を確認してください。
```

## 5. 作業を追跡する

実行が始まると、同じ会話内で次の情報が更新されます。

- Claude Codeが現在行っている作業
- ツール実行とTodo
- 権限要求
- 経過時間とコスト
- 変更ファイル数
- 完了回答

回答本文は認証付きSSEで逐次配信されます。完了後はOpen WebUI標準のMarkdown
レンダラーへ渡されるため、見出し、太字、リスト、コード、表をチャット回答として
読めます。

## 6. 差分を確認する

タスク完了後に「変更内容を確認」を開きます。新規ファイルを含む
repository-relative pathとdiffが表示されます。

各タスクは専用worktreeで動くため、ここで見える変更は自動で`main`へ入りません。
内容を確認してから、今後追加されるcommit・push・Pull Requestフロー、または
通常のGit操作で採用します。

## 7. 権限要求に対応する

確認が必要なツールをClaude Agent SDKが要求すると、OpenMはタスクを
`waiting_permission`へ移します。

- **今回のみ許可:** その要求だけを許可
- **このタスクで許可:** 同種の要求をタスク中に許可
- **拒否:** 実行を拒否

パッケージ導入や影響範囲の広いコマンドは、内容を読んでから判断してください。

## 8. 停止と再起動

```powershell
docker compose --env-file .env.openm -f docker-compose.openm.yaml down
docker compose --env-file .env.openm -f docker-compose.openm.yaml up -d
```

`openm-data` volumeを削除しない限り、ユーザー情報、Workspace、タスク履歴、
worktreeは保持されます。

## 次に読むもの

- [v0.1.0リリースノート](../releases/v0.1.0.md)
- [OpenM仕様・実装計画書](../openm-specification.md)
- [検証レポート](../openm-validation.md)
