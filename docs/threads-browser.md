# Threads ブラウザー版（開発中）

Threads の本文・投稿時刻のみを診断する読み取り専用経路。画像は未対応で、投稿の実削除はしない。モックは架空投稿のみで、Meta やモデルに接続しない。実投稿は現在、既存のローカル Ollama 本文抽出経路を使う。チーム管理 GPU への実投稿送信は実装・運用確認が必要。

## テスター向け設定

Meta アプリの Threads API 設定で OAuth redirect URI に `https://<公開オリジン>/api/threads/callback` を正確に登録し、Threads テスターを登録して招待を承諾する。同じ URL を `THREADS_CALLBACK_URL`、そのオリジンを `THREADS_PUBLIC_ORIGIN` に設定する。`THREADS_CLIENT_ID` と `THREADS_CLIENT_SECRET` はサーバー側にのみ設定。`COOKIE_SECURE=1`、`THREADS_ENABLED=1` が必要。Next.js、CloudFront、リバースプロキシ等の全経路でコールバックのクエリをログに記録しないことを実際に確認してから `THREADS_QUERY_LOGS_REDACTED=1` にする。API の uvicorn ログは該当クエリを除去するが、上流のログ設定は別途必要。公開オリジンが未確定のため、実際に登録する URL はまだ確定できない。

テスター限定での動作は一般利用者向けの公開承認とは別。一般公開には Meta の該当権限・アプリ審査と運用条件を確認する。認証の拒否・期限切れでは再ログインする。セッションは最大30分、ログアウトでも破棄する。実テスター OAuth、ログ保護、CloudFront 経路、実投稿診断はまだ未検証。

[Meta 公式 Threads API コレクション](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api) の認可コード交換と `threads_basic` を参照。
