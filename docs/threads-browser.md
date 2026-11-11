# Threads ブラウザー版：テスター限定の実認証準備

Threads の本人投稿の本文と投稿時刻を読む。画像は診断しない。投稿の実削除は行わず、仮除外と再診断だけを行う。トークン・投稿・診断結果は API プロセスのメモリに最大30分保持し、ログアウトでも消す。`THREADS_ENABLED=0` が既定なので、配備しただけでは実 OAuth は公開されない。

ログイン後の「本人投稿を確認」は `GET /api/threads/posts` を使い、AIモデルが未稼働でも本人IDを再照合して投稿を表示する。診断はその後に別操作で始める。

## 確認済みの公開経路

2026-11-11 に AWS の CloudFront 配信 `d2qyby5y8mc03f.cloudfront.net` を読み取り確認した。登録する URL は **`https://d2qyby5y8mc03f.cloudfront.net/api/threads/callback`**。`/api/*` は HTTPS 強制、非キャッシュ、全 viewer ヘッダー・Cookie・クエリを VPC origin の web:3000 に転送し、Next.js の rewrite が api:8001 に中継する。CloudFront 標準アクセスログは無効、FastAPI の本番コンテナは `--no-access-log` で動く。現行 WAF はリクエストサンプリングが有効で、認可コードを含むクエリがサンプルに残る可能性がある。`infra/terraform/edge.tf` にサンプリングを無効化する差分を用意したが、AWS にはまだ適用していない。Next.js とコンテナのリクエスト時ログも配備後の実測が必要。2026-11-11 現在の公開 `/threads` は 404（このブランチは未配備）。

## Meta 管理画面で必要な設定

1. 対象の既存アプリで **Use cases → Access the Threads API → Customize → Settings / Client OAuth Settings** を開き、**Valid OAuth Redirect URIs** に `https://d2qyby5y8mc03f.cloudfront.net/api/threads/callback` を登録する。末尾の `/` を足さない。Web OAuth Login と Client OAuth Login がある場合は有効にする。
   同じ画面の **Deauthorize / Uninstall callback URL** には `https://d2qyby5y8mc03f.cloudfront.net/api/threads/deauthorize`、**Data Deletion Requests / Delete callback URL** には `https://d2qyby5y8mc03f.cloudfront.net/api/threads/data-deletion` を登録する。これらは OAuth のコールバックとは別の URL。Meta の署名付き POST を検証して、該当ユーザーのセッションと診断結果を即時破棄する。データ削除依頼には確認コードと公開状況ページを返す。
2. **App settings → Basic** の **Threads App ID / Threads App Secret** を使用する。通常の Meta App ID / Secret とは別。値はチャット、Git、ブラウザーに出さず、アプリ EC2 のサーバー側設定にだけ渡す。環境変数は `THREADS_APP_ID` と `THREADS_APP_SECRET`。
3. 既存テスターは **App roles → Roles → Threads Tester** で登録・承認済みか確認する。招待が Pending なら、本人が Threads の **Settings → Account → Website permissions → Invites** から承諾する。要求権限は `threads_basic` のみ。

テスターが使える範囲と一般公開は別。一般ユーザーに許可するには Meta の App Review と公開手続きが必要。Meta の [公式サンプル](https://github.com/fbsamples/threads_api) と [公式 API コレクション](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api)を参照。

## AWS 側の最小設定差分

`infra/aws.env.example` に必要なキーを追加した。実配備時に `THREADS_PUBLIC_ORIGIN=https://d2qyby5y8mc03f.cloudfront.net`、`THREADS_CALLBACK_URL=https://d2qyby5y8mc03f.cloudfront.net/api/threads/callback`、Threads 専用 App ID/Secret、`COOKIE_SECURE=1` を設定する。WAF サンプリング停止の Terraform 差分をレビューして適用し、ログを検証するまで `THREADS_ENABLED` と `THREADS_QUERY_LOGS_REDACTED` は 0 のまま。実診断には API と同じホストから Ollama の `qwen3:4b-instruct` が必要。AWS の既存 compose に Ollama はないため、CPU 経路を配備するか、チーム管理 GPU の送信先・アクセス制御・ログ・保存条件を確認して別途実装する。GPU は承認前に起動しない。

## 検証状況

既存テスタートークンで `/me` と本人の本文付き投稿3件を取得でき、ローカル CPU/Ollama で手がかり3件・推定1件を抽出できた（本文、トークン、推定値は出力していない）。合成投稿のブラウザーE2Eと、OAuth の state・Cookie・一回限りのコールバックの API テストは成功した。2026-11-11 にテスターから Meta のコールバック設定を保存できたとの報告を受けた。登録値の読み取り確認と、実 Meta の認可画面・コード交換、公開 CloudFront 経由のコールバックは、このブランチの配備前なので未検証。
