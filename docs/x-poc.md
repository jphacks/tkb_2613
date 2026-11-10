# X連携の実装と運用条件（2026-11-10）

## 実装範囲

`poc/x-local-text` の `/x` 画面と `/api/x/*` は Bluesky のセッション・OAuth・診断ルートから独立している。X OAuth 2.0 PKCE（S256）で本人を認証し、`/2/users/me` で得た本人 ID の投稿だけを取得する。本文・投稿ID・日時を共通 `Post` に変換し、既存の `Clue` 抽出・推論・仮除外へ渡す。画像と実削除は扱わない。実X投稿の本文はローカルOllamaだけに送り、X経路は既存のモデル送信先ガードを使って許可先を loopback に固定している。架空投稿のGPUデモは別セッションで動く。

X専用セッション、OAuth state・PKCE verifier、トークン、投稿、結果はサーバープロセスのメモリにだけ置く。Cookie にはランダムなセッションIDだけを入れる。セッション期限は既定30分で、ログアウト時には即座に消す。OAuthコールバックの `code`・`state` は uvicorn のアクセスログで伏せる。ただし、上流のプロキシやホスティング基盤でもクエリ文字列をログに記録しない設定を確認してから実認証を有効にする。

`X_MOCK_MODE=1`（既定）では架空の投稿・手がかりで、認証を使わず画面・診断・仮除外・再診断を試せる。実Xへのアクセスは `X_USE_CASE_APPROVED=1`、`X_PAID_READS_APPROVED=1`、`X_QUERY_LOGS_REDACTED=1`、`X_MOCK_MODE=0`、Client ID の全条件を満たすときだけ開始できる。これらのフラグは許可の代わりにはならず、許可・費用承認と上流ログ設定の確認が先に必要。

`X_GPU_DEMO_ENABLED=1` と `X_MOCK_MODE=1` を同時に設定すると、固定の架空X投稿だけを `VLM_BASE_URL` の既存GPUモデルへ送る別ボタンが出る。`MODEL_ALLOWED_HOST_SUFFIXES` にはチームが確認した正確なホストだけを指定する。X APIは呼ばず、トークンも持たない。実X投稿はこの設定に関係なく従来のローカルOllama経路に限定する。GPUを使った仮除外・再診断は抽出済みの手掛かりだけで計算し、再送しない。

## 公式仕様・料金・レート

- [OAuth 2.0 PKCE](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code): `tweet.read users.read` だけを要求する。`offline.access` は要求せずリフレッシュトークンを保持しない。X Developer Console にコールバックURLを完全一致で登録する。Web App は Client Secret をサーバー内だけに設定する。
- [本人確認](https://docs.x.com/x-api/users/get-my-user)と[本人の投稿取得](https://docs.x.com/x-api/users/get-posts): `/2/users/me`、`/2/users/:id/tweets`。リポストを除外し、返された `author_id` を本人IDと照合する。読み取りは1セッション1回で結果をメモリから復元する。
- [料金](https://docs.x.com/x-api/getting-started/pricing): User Read `$0.010`/件、Posts Read `$0.005`/件（変更あり）。本人確認1件＋最大30投稿なら概算 `$0.16`（税など別）。本文なし投稿も課金対象なので取得リソース数を最大30に抑える。投稿数を1〜4件に設定した場合もAPIの最小ページサイズ5件分が請求されうる。実行前にDeveloper Consoleの最新単価・残高・支出上限を確認する。
- [レート制限](https://docs.x.com/x-api/fundamentals/rate-limits): 現行の表では `/2/users/me` はユーザーごと75回/15分、`/2/users/:id/tweets` はユーザーごと900回/15分。429は再試行せず503と `Retry-After: 900` を返す。Xの実際の残量・リセット時刻は応答ヘッダーとConsoleで確認する。

## 設定

`.env.example` の `X_*` 設定を参照。実認証には `X_CLIENT_ID`、Web Appの場合は `X_CLIENT_SECRET`、公開サイトの `X_PUBLIC_ORIGIN`、Developer Consoleに登録した完全一致の `X_CALLBACK_URL` を設定する。公開HTTPSでは `COOKIE_SECURE=1`。`X_MAX_POSTS` は最大30。`OLLAMA_BASE_URL` はAPIプロセスから見える loopback の Ollama を指定する。Docker内からホストのOllamaへ接続する構成は、送信先ガードを緩める前に別途設計・検証する。Xトークンや秘密鍵を `NEXT_PUBLIC_` 変数、Git、ログに入れない。

## 利用規約の判断

- [Developer Policy](https://docs.x.com/developer-terms/policy) は利用者の理解と明示的同意を求め、**ログインだけでは同意にならない** とする。画面には診断内容と送信先を説明する同意欄を設けた。
- [Developer Agreement](https://docs.x.com/developer-terms/agreement) は X Content の分析を **Xが明示的に承認した用途** に限定し、個人の非公開情報の導出と、X Contentに含まれる位置情報の切り離し・蓄積を制限する。モデル学習・ファインチューニングも禁止する。
- [Restricted Uses](https://docs.x.com/developer-terms/restricted-use-cases) は **individual profiling** を禁止用途として挙げ、健康・政治信条などのセンシティブ属性の推定も禁止する。本人が同意する自己診断なら例外になるという記載は確認できない。みーつけたのプロフィール推定が許されるとは判断できないため、Xから用途の書面承認を得るまで実投稿を診断モデルへ入力しない。
- Xコンテンツを第三者の外部推論サービスへ渡す場合は、同じ[契約](https://docs.x.com/developer-terms/agreement)の第三者提供制限と[再配布条件](https://docs.x.com/developer-terms/restricted-use-cases)が関係する。診断本文・投稿ID・推定結果の送信先、事業者の保存・再利用・学習条件、削除・変更時の同期を確認し、Xの許可を得るまでは外部GPUに送らない。現実装のX経路は loopback Ollama のみ。

**結論:** 本人同意だけでは実X投稿を用いたみーつけたの推論を許可済みとは言えない。Award Dayでは架空投稿のX画面を実演し、実X連携は用途許可後に限る。

## テストと残作業

`api/tests/test_x_app.py` は合成投稿でPKCE、本人確認、投稿取得、Ollama応答、推論、仮除外、再診断を通す。`web/src/app/x/page.test.tsx` は画面操作を通す。テスト中のX APIとOllamaはHTTPモックで、実課金・実送信はない。

架空投稿1件をローカルの `qwen3:4b-instruct` に実際に渡す手動E2Eも実施した。1手がかり・1推定が得られ、所要時間は31.96秒だった（この1回の環境での測定）。X APIには接続していない。

実投稿試験には (1) Xの用途承認、(2) 費用の事前承認、(3) Developer Consoleの設定と支出上限、(4) 本人の明示同意、(5) ローカルOllamaへの安全な接続、(6) 上流アクセスログのクエリ伏せ、(7) 削除・変更・保護化への同期運用が必要。Xの画面とAPIはBluesky/Threadsのセッションから独立している。共通化できるのは `Post[]` 以降の抽出・推論処理で、認証・取得・利用規約は各社別に扱う。

### Award Day用のブラウザーテスト（合成データのみ）

`web/e2e/x-demo.spec.ts` はビルド済み `/x` と `X_MOCK_MODE=1` のFastAPIを実ブラウザーで操作する。診断・根拠・仮除外・再診断・ログアウトを通し、OAuth開始はブラウザー内でX画面への移動をモックする。認証失敗、503、504の表示とBlueskyホームの表示も確認する。Xのサーバーには接続しない。

再現手順：`make setup` 後、APIを `MOCK_MODE=1 X_MOCK_MODE=1` でポート8001に起動し、`web/` で `pnpm exec playwright install chromium`（初回のみ）、`pnpm build`、`mkdir -p .next/standalone/.next/static && cp -a .next/static/. .next/standalone/.next/static/`、`HOSTNAME=127.0.0.1 PORT=3000 node .next/standalone/server.js` を順に実行する。静的アセットはサーバー起動前に配置する。別の端末で `web/` から `pnpm test:e2e:x` を実行する。`API_ORIGIN` の既定は `http://localhost:8001` で、ビルド時にNext.jsの中継先へ設定される。Dockerfileはビルド時に静的アセットをコピーする。OAuthの実フローと有料APIはこのテストの対象外。

### 実X投稿の利用前に確認する条件

Xの[Agreement](https://docs.x.com/developer-terms/agreement)はX Contentの分析をXが明示的に承認した用途に限定し、個人の非公開情報の導出を禁止する。[Restricted Uses](https://docs.x.com/developer-terms/restricted-use-cases)は individual profiling を禁止用途に挙げる。現在の16項目には自宅・勤務先・生活行動などの推定が含まれるため、**現実装をそのまま有効化してよいとは判断できない**。Xからこの具体的な自己診断用途と出力項目について書面で回答を得る。許容範囲が限定される場合はX専用の推論項目・表示を狭め、非公開情報や禁止属性を推定しないことをテストで確認する。許可が得られない場合は合成デモだけに留める。

本人の明示同意、送信先（ローカルOllama）、メモリ保持時間、ログ、削除・変更・保護化への対応、表示要件を用途説明に含める。外部GPUへ送る場合は事業者名、保存・学習・再利用条件、第三者提供の扱いを別途Xに確認する。API単価と上限は実行直前にDeveloper Consoleで確認し、課金の事前承認を得る。

### Xへの用途確認文案（未送信）

> 件名：本人同意による自己投稿のプライバシー診断用途の確認
>
> X Developer Policy Team ご担当者様
>
> 私たちは、利用者がOAuth 2.0 PKCEで自分のXアカウントにログインし、明示的に同意した場合に限り、本人の直近最大30投稿の本文と投稿時刻を取得して、投稿に書かれた手掛かりと根拠を本人に示す教育用アプリを検討しています。投稿の削除・変更は行いません。処理は当チームが管理するローカルOllamaで行い、外部推論サービスやモデル学習には使用しません。トークン・投稿・結果はサーバーのメモリに最大30分保持し、ログアウト時に消去します。投稿ごとの仮除外と再診断は保存済みの結果だけで行います。
>
> 本アプリが投稿を組み合わせて居住地域、通勤、勤務先、生活パターン等を推定する場合、Developer Agreementの分析用途承認、非公開情報の導出禁止、およびRestricted Usesのindividual profilingの制限に照らして、本人同意があっても許可される範囲はありますか。許可可能な観測・表示項目と、禁止すべき推定項目を具体的にご教示ください。書面による用途承認が必要な場合の申請窓口・手続きもご案内ください。外部推論サービスを将来利用する場合の第三者提供条件も確認したいと考えています。
>
> 回答を得るまでは実X投稿を診断モデルへ入力せず、架空投稿のみで実演します。
