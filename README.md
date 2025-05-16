# Slack Export Tool
このツールは、Slackチャンネルの指定した時間区間の投稿をJSON形式でエクスポートするPythonプログラムです。スレッドの返信やリアクションも含め、構造化されたデータを出力します。
(Created with Claude AI)

## 機能

- 指定したSlackチャンネルから特定の時間区間のメッセージを取得
- スレッド返信とリアクションを含むメッセージの取得
- ユーザー情報の取得と紐付け
- 日本語と絵文字に対応
- 構造化されたJSON出力
- APIレート制限に対するリトライ処理
- Docker対応

## 必要条件

- Python 3.7以上
- Slack APIトークン（Bot Token推奨）
- Dockerがインストールされていること（Docker使用時）

## インストールと使用方法

### 1. 直接実行する場合

```bash
# 必要なパッケージをインストール
pip install -r requirements.txt

# プログラムを実行
python slack_exporter.py --channel チャンネル名 --token xoxb-xxx-xxx --start 2023-01-01T00:00:00 --end 2023-01-31T23:59:59 --output export.json
```

### 2. Dockerを使用する場合

```bash
# Dockerイメージをビルド
docker build -t slack-exporter .

# Dockerコンテナを実行
docker run --rm -v $(pwd):/app slack-exporter --channel チャンネル名 --token xoxb-xxx-xxx --start 2023-01-01T00:00:00 --end 2023-01-31T23:59:59 --output /app/export.json
```

## Slack APIトークンの取得方法

1. [Slack API アプリケーションページ](https://api.slack.com/apps)にアクセス
2. 「Create New App」をクリック
3. 「From scratch」を選択し、アプリ名とワークスペースを設定
4. 「OAuth & Permissions」セクションで以下の権限（スコープ）を追加:
   - `channels:history` - パブリックチャンネルの履歴閲覧
   - `channels:read` - パブリックチャンネル情報の取得
   - `groups:history` - プライベートチャンネルの履歴閲覧（必要に応じて）
   - `groups:read` - プライベートチャンネル情報の取得（必要に応じて）
   - `reactions:read` - リアクション情報の取得
   - `users:read` - ユーザー情報の取得
5. 「Install to Workspace」をクリックしてアプリをインストール
6. 発行された「Bot User OAuth Token」（`xoxb-`から始まる）を使用

## パラメータ一覧

| パラメータ | 短縮形 | 説明 | デフォルト |
|----------|-------|------|----------|
| `--channel` | `-c` | エクスポートするSlackチャンネル名 | 必須 |
| `--token` | `-t` | SlackのAPIトークン | 必須 |
| `--start` | `-s` | 開始時間 (YYYY-MM-DDTHH:mm:ss形式、JST) | 必須 |
| `--end` | `-e` | 終了時間 (YYYY-MM-DDTHH:mm:ss形式、JST) | 必須 |
| `--output` | `-o` | 出力JSONファイル名 | slack_export.json |
| `--verbose` | `-v` | 詳細なログ出力 | False |
| `--pretty` | `-p` | 整形されたJSON出力（読みやすいが大きくなります） | False |

## 出力JSONの構造

出力されるJSONファイルは以下の構造になっています：

```json
{
  "channel": {
    "id": "チャンネルID",
    "name": "チャンネル名",
    "topic": "チャンネルトピック",
    "purpose": "チャンネル目的"
  },
  "time_range": {
    "start": "開始時間（ISO形式）",
    "end": "終了時間（ISO形式）"
  },
  "messages": [
    {
      "type": "メッセージタイプ",
      "user": "ユーザーID",
      "user_info": {
        "id": "ユーザーID",
        "name": "ユーザー名",
        "real_name": "実名",
        "display_name": "表示名"
      },
      "text": "メッセージテキスト",
      "ts": "タイムスタンプ",
      "reactions": [
        {
          "name": "リアクション名",
          "count": リアクション数,
          "users": ["ユーザーID1", "ユーザーID2", ...],
          "user_details": [
            {
              "id": "ユーザーID",
              "name": "ユーザー名",
              "real_name": "実名",
              "display_name": "表示名"
            },
            ...
          ]
        },
        ...
      ],
      "replies": [
        {
          "user": "ユーザーID",
          "user_info": {
            "id": "ユーザーID",
            "name": "ユーザー名",
            "real_name": "実名",
            "display_name": "表示名"
          },
          "text": "返信テキスト",
          "ts": "タイムスタンプ",
          ...
        },
        ...
      ],
      ...
    },
    ...
  ],
  "users": {
    "ユーザーID1": {
      "id": "ユーザーID",
      "name": "ユーザー名",
      "real_name": "実名",
      "display_name": "表示名"
    },
    ...
  },
  "metadata": {
    "total_messages": メッセージ総数,
    "total_thread_replies": スレッド返信総数,
    "total_unique_users": ユニークユーザー数,
    "export_time": "エクスポート実行時間（ISO形式）",
    "exporter_version": "エクスポーターバージョン"
  }
}
```

## 注意事項

- APIのレート制限に対応するためのリトライ処理を実装していますが、大量のメッセージを含むチャンネルの場合は処理に時間がかかる場合があります。
- プライベートチャンネルにアクセスするには適切な権限を持つトークンが必要です。
- スレッド返信とリアクションは、投稿時間が指定時間区間外でも取得されます。
- 出力JSONファイルのサイズは、メッセージ量に応じて大きくなる場合があります。

## トラブルシューティング

- **認証エラー**: トークンが正しいかどうか、必要な権限が付与されているかを確認してください。
- **チャンネルが見つからない**: チャンネル名の綴りを確認し、APIトークンがそのチャンネルへのアクセス権を持っているか確認してください。
- **レート制限エラー**: 大量のメッセージを扱う場合は、自動的にリトライされますが、処理時間が長くなる場合があります。
- **日時形式エラー**: 日時は必ず `YYYY-MM-DDTHH:mm:ss` 形式で指定してください。

## ライセンス

MIT