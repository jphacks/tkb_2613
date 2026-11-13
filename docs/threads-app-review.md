# Threads App Review 提出資料（`threads_basic`）

最終確認日: 2026-11-12（日本時間）

対象アプリは、ログインした本人のThreads投稿を取得して一覧・詳細表示し、公開されている情報を本人が確認できるセルフチェック「みーつけた」。審査で実演するセルフチェックはブラウザ内の固定ルールで動き、AIではない。任意のAI診断は別機能であり、現在の本番ではモデル停止中のため審査手順に含めない。申請権限は現行実装が使う `threads_basic` だけにする。Threads画面は日本語（既定）と英語を切り替えられ、審査動画と審査員の操作は英語表示（`/threads?lang=en`）で行う。英語表示は審査後も残す。

公式問い合わせ先: `komekami7110@gmail.com`

## 実装調査の結果

| 項目 | 現行実装 |
| --- | --- |
| OAuth権限 | 認可URLの `scope` は `threads_basic` だけ。投稿・返信・インサイト・削除用の権限は要求しない。 |
| ユーザー情報 | `GET https://graph.threads.com/v1.0/me?fields=id,username` で、ログイン本人のThreadsユーザーIDとユーザーネームを取得する。コード交換時に返る `user_id` と `/me` のIDも照合する。 |
| 投稿情報 | `GET /me/threads?fields=id,text,timestamp,media_type` で、本文のある本人投稿を新しい方から最大30件取得する。ページングにはMetaが返すcursorだけを使う。画像・動画URLやバイナリは取得せず、画面へ保持するのは投稿ID・本文・投稿時刻。 |
| 固定ルールのセルフチェック | `GET /api/threads/posts` で取得済みの本文をブラウザ内で確認し、URL・メールアドレス・電話番号・郵便番号・`@`ユーザーネームらしき文字列との一致だけを示す。追加の外部送信やモデル呼出しはなく、所有者・実在性・意味を推定しない。 |
| 任意のAIへの送信 | 利用者が一覧取得とは別に「AI診断を試す」を押し、かつモデルが稼働している場合だけ、実Threads投稿の本文を、Blueskyと同じチーム管理のvLLM（`VLM_BASE_URL`。送り先は `MODEL_ALLOWED_HOST_SUFFIXES` で限定）へ送る。`THREADS_TEXT_BACKEND=ollama` のときだけ `OLLAMA_BASE_URL` のOllamaへ送る。投稿ID・ThreadsユーザーID・画像は送らない。診断の前にモデルの応答を確かめ、応答がなければ送らずに503を返す。 |
| AIの実行場所 | 2026-11-13から既定はBlueskyと同じAWSのプライベートGPU上のvLLM（`THREADS_TEXT_BACKEND=vlm`）。以下は変更前（Ollama既定）の記録：2026-11-12の読み取り専用確認では、本番APIコンテナからOllamaへ到達できず、GPUインスタンスも停止中だったため、実ThreadsのAI診断は現状完走できない。 |
| セッション保存 | アクセストークン、ユーザーID、ユーザーネーム、投稿、手がかり、診断結果はFastAPIプロセスのメモリのみ。Threads経路から共有結果SQLiteへ書く処理はない。CookieはランダムなセッションIDだけ。 |
| 保持期間 | セッション作成から最大30分（`SESSION_TTL_MINUTES` が長くてもThreadsは1800秒上限）。OAuth開始情報は最大5分。アクセスによる延長はない。プロセス再起動でも消える。 |
| 終了時の削除 | `DELETE /api/threads/session` はCookieのセッションをメモリから削除する。期限時も削除する。Metaの認証解除・データ削除通知は、署名を検証して同じowner IDの全セッションを削除する。ブラウザを閉じるだけでは即時削除にならず、期限まで残り得る。 |
| 認証解除 callback | `POST /api/threads/deauthorize`。`signed_request` をThreads App SecretでHMAC-SHA256検証し、対象ユーザーの全セッションを削除する。 |
| データ削除 callback | `POST /api/threads/data-deletion`。同じ検証・削除後、公開状況ページURLとランダムな確認コードを返す。確認コード・依頼履歴は永続保存しないため、後から個別照会する機能はない。 |
| ログ | アプリ独自ログは件数、手がかり件数、失敗件数、処理段階、所要時間を出す。投稿本文・画像・トークンを意図的に出す処理はない。OAuth callbackのqueryはuvicorn access log filterで除去する。本番はFastAPI access logとCloudFront標準access logを無効化する構成。コンテナログは10MB×3ファイルで回転する。リクエスト時ログに秘密が混じらないことは本番で再確認する。 |
| 表示言語 | Threads画面は日本語（既定）と英語。画面上部の切り替え、または `/threads?lang=en` で選ぶ。選択はブラウザの `localStorage` に保存し、Threads認可画面から戻っても保つ（トークン・投稿は保存しない）。投稿本文・ユーザー名・投稿IDは取得したまま表示し、翻訳しない。APIと診断の処理は言語に依らず同じ。公開ページ（`/privacy` など）とフッターは日本語のみ。 |
| 既存公開文書 | `/privacy`、`/terms`、`/contact` は存在したがBluesky中心だった。今回Threadsの処理を反映し、`/data-deletion` と `/support` を追加した。 |

ThreadsのAPI処理は `api/src/tkb_api/routes/threads.py` と `api/src/tkb_api/threads_poc.py`、モデル処理は `detect/src/tkb_detect/vlm_client.py`（`THREADS_TEXT_BACKEND=ollama` のときは `ollama_client.py`）、セッション期限は `api/src/tkb_api/config.py` を根拠に確認した。

## `threads_basic` が必要な理由（Dashboard貼り付け用・英語）

> Miitsuketa is a privacy self-audit tool for the person who signs in. We request `threads_basic` so the user can connect their own Threads account and read their own Threads user ID, username, and up to 30 of their own recent text posts with IDs, timestamps, and media-type metadata. The app verifies that the posts belong to the authenticated user, displays the post text, ID, and timestamp, and offers a deterministic on-device check for visible patterns such as URLs or contact-like strings. This check does not use AI, does not determine who a string belongs to, and does not send the post to another service. The app does not read other users' feeds, retrieve Threads media URLs or media bytes, publish, edit, or delete Threads content, or access replies or insights. Threads content and the access token are held in server process memory for at most 30 minutes and are removed on logout, session expiry, or a valid deauthorization/data-deletion callback.

短い入力欄向け:

> We use `threads_basic` to authenticate the user and read only that user's ID, username, and up to 30 of their own text posts with IDs, timestamps, and media-type metadata. We display the post text, ID, and timestamp so the user can review details and run a deterministic, non-AI check for directly visible URL or contact-like patterns. We do not publish, edit, delete, retrieve media URLs or bytes, access replies or insights, or read other users' content.

## 審査員向け操作手順（Dashboard貼り付け用・英語）

Reviewer credentials must be supplied only through Meta's secure reviewer-credential fields. Do not place passwords or access tokens in this document, GitHub, or the review description.

The Threads page has a built-in English display. Open it directly in English with `https://d2qyby5y8mc03f.cloudfront.net/threads?lang=en`, or press **English** in the **日本語 / English** switch at the top of the page. The choice is saved in the browser and is kept after the Threads authorization screen, so the whole flow below stays in English. Japanese is the default when no choice has been made, and the English display stays available after the review. Post text, the username, and post IDs come from Threads and are shown as retrieved; they are never translated.

1. Open `https://d2qyby5y8mc03f.cloudfront.net/threads?lang=en` in a desktop or mobile browser. No login is required to open the page.
2. Read the notice explaining that the app retrieves the signed-in user's own Threads post text and timestamps for display and a non-AI public-information check. Check the consent checkbox.
3. Click **“Log in with Threads”**. The browser opens the official Threads authorization screen. Sign in with the reviewer account provided in the secure review fields and approve only `threads_basic`.
4. After authorization, the app returns to `/threads` in English and shows the connected `@username`.
5. Click **“Review my posts”**. The app calls `/me` and `/me/threads`, verifies that the returned owner ID matches the authenticated user, and displays up to 30 of that user's text posts and timestamps. While a request is running, the page shows **“Working…”**.
6. Expand **“Retrieved data details”** under a post. The app displays the post ID and exact timestamp and states that only the media type was requested, not image/video URLs or data.
7. Click **“Check visible public information”** in the **“Public-information self-check (not AI)”** section. The browser applies fixed text patterns to the already displayed posts and shows direct matches such as URL-like or contact-like strings. The screen states that this is not AI and does not infer ownership or meaning.
8. Do not open **“Optional: AI diagnosis (only while the model is running)”** for this review. It is not needed to demonstrate `threads_basic`, and the production model is currently unavailable. If it is run anyway, the page reports that the model is unavailable and the steps above keep working.
9. Click **“Log out”**. The app deletes the in-memory session containing the access token, user information, and fetched posts.

Scope of the English display: the Threads page, its notices, and its error messages are translated. The site footer links and the public pages `/privacy`, `/terms`, `/data-deletion`, and `/support` are currently Japanese only.

審査用アカウントには、本文と投稿時刻を確認できる投稿を2件以上用意する。セルフチェックを分かりやすくする場合は、架空のURLや `@sample` など秘密情報ではない文字列を1件に含める。実在個人の秘密情報は使わない。

## スクリーン録画チェックリスト

### 撮影台本（2分前後の目安）

| 時刻 | 操作と映すもの | 英語字幕・ナレーション例 |
| --- | --- | --- |
| 0:00–0:12 | ログアウト済みのブラウザで本番 `/threads?lang=en` を開く（または右上で **English** を押す）。アドレスバー、英語の取得対象の説明、同意欄を映す。 | “Miitsuketa is a privacy self-audit for the signed-in user's own Threads posts.” |
| 0:12–0:30 | 同意をチェックして **“Log in with Threads”** を押す。公式Threads認可画面でアプリ名と要求権限を映し、テストユーザーで許可する。パスワード入力部分は停止・カットする。 | “The app requests only `threads_basic`.” |
| 0:30–0:43 | 英語表示のまま `/threads` に戻り、接続した `@username` を映す。 | “The returned user ID is checked against the authenticated user.” |
| 0:43–1:05 | **“Review my posts”** を押し、本人の本文投稿と投稿時刻が2件以上表示されるところまでスクロールする。投稿本文とユーザー名は翻訳されない。 | “The app reads only this user's ID, username, and up to 30 text posts. It does not retrieve media URLs or bytes.” |
| 1:05–1:18 | 1件の **“Retrieved data details”** を開き、投稿ID、正確な投稿時刻、メディア未取得の表示を映す。 | “The user can inspect the exact data retrieved for each of their own posts.” |
| 1:18–1:38 | **“Check visible public information”** を押し、固定パターンの結果と “not AI” の表示を映す。 | “This deterministic browser-side check uses no AI and makes no inference about ownership or meaning.” |
| 1:38–1:50 | **“Log out”** を押し、未接続状態へ戻るところを映す。 | “Logout removes the access token and fetched posts from the in-memory session.” |
| 1:50–2:10 | アドレスバーから `/privacy`、`/data-deletion`、`/support` を順に直接開き、ログインなしで読めることを短く映す。 | “Public privacy, data-deletion, and support information is available without login.” |

撮影前にブラウザの通知、ブックマーク、個人用プロフィール画像を隠し、ズームを100%前後にする。認証情報の入力は録画外で済ませるか編集で完全に除き、開発者ツール、ネットワークヘッダー、Meta Dashboardの秘密値は映さない。画面は英語表示のまま撮影し、字幕は画面の英語表記を補う程度にする。日本語表示のまま撮る場合は、日本語のボタン名が上表の英語字幕と同じ意味になるようにする。

### 提出前チェック

- [ ] 本番URL `/threads?lang=en` をアドレスバーに表示する（localhostやモック診断を使わない）。
- [ ] 画面上部の **English** が選択状態（押下状態）になっていて、認可画面から戻っても英語のままであることを映す。
- [ ] 録画開始時はログアウト状態にする。
- [ ] 同意文で「本人投稿本文と投稿時刻」「画像は対象外」「AIを使わないセルフチェック」が読めるようにする。
- [ ] **“Log in with Threads”** を押し、公式Threads認可画面と要求権限を映す。
- [ ] パスワード、アクセストークン、App Secret、開発者ダッシュボードの秘密値は映さない。
- [ ] 戻った画面の接続ユーザーネームを映す。
- [ ] **“Review my posts”** を押し、本人の投稿がアプリに表示されるところを映す。
- [ ] **“Retrieved data details”** を開き、投稿ID、投稿時刻、メディア未取得を映す。
- [ ] **“Check visible public information”** を押し、固定ルールでありAIではないことを字幕で明示する。
- [ ] 任意のAI診断は開かず、動画説明にも審査対象機能として含めない。
- [ ] ログアウトまで映し、セッションデータが削除されることを字幕で説明する。
- [ ] `/privacy`、`/data-deletion`、`/support` がログインなしで開くことを短く映す。
- [ ] 英語表示で撮影するため、ボタンの字幕は不要。ただし投稿本文（日本語のまま表示される）が映る場合は、英語の注釈を添える。
- [ ] 1080p程度で文字とクリック位置を読めるようにし、`threads_basic` の利用証明に不要な操作は省く。
- [ ] 提出前に無音で再生し、初見の審査員が認可→本人投稿取得→詳細表示→セルフチェック→破棄を理解できるか確認する。

## Meta Dashboardへ入力する公開URL

| Dashboard項目 | URL |
| --- | --- |
| App website / Website URL | `https://d2qyby5y8mc03f.cloudfront.net/` |
| Privacy Policy URL | `https://d2qyby5y8mc03f.cloudfront.net/privacy` |
| Terms of Service URL | `https://d2qyby5y8mc03f.cloudfront.net/terms` |
| User Data Deletion Instructions URL | `https://d2qyby5y8mc03f.cloudfront.net/data-deletion` |
| Support / Contact URL | `https://d2qyby5y8mc03f.cloudfront.net/support` |
| Valid OAuth Redirect URI | `https://d2qyby5y8mc03f.cloudfront.net/api/threads/callback` |
| Deauthorize / Uninstall Callback URL | `https://d2qyby5y8mc03f.cloudfront.net/api/threads/deauthorize` |
| Data Deletion Request Callback URL | `https://d2qyby5y8mc03f.cloudfront.net/api/threads/data-deletion` |
| Data deletion status URL returned by callback | `https://d2qyby5y8mc03f.cloudfront.net/threads/data-deletion-status` |
| App contact / Support email | `komekami7110@gmail.com` |

URLは末尾スラッシュを勝手に足さず、Dashboardの保存後に表示値を読み直す。公開説明ページとcallback URLは別物なので、Data Deletion欄が「instructions URL」か「callback URL」かを見て対応する値を入れる。

## データ削除対応の説明（英語）

> Threads access tokens, user IDs, usernames, fetched posts, extracted clues, and diagnosis results are stored only in the API process memory for a maximum of 30 minutes. They are removed when the user logs out, when the session expires, when the process restarts, or when Meta sends a valid deauthorization or data-deletion signed request. The callbacks verify the HMAC-SHA256 signature with the Threads App Secret before deleting every active in-memory session for the user ID. The data-deletion callback returns a confirmation code and a public status-page URL. We do not use a persistent database for Threads posts or diagnosis results. The callback confirmation code and request history are not persisted, so the status page cannot look up an individual request. The deletion removes app-held session data; it does not delete the user's Threads posts or Threads account.

Support and privacy contact: `komekami7110@gmail.com`

## 必須項目と未完了項目

### 実装・ローカルテストで確認済み

- `threads_basic` だけを要求し、`/me` と `/me/threads` だけを読む。
- 本人ID照合、stateと短命Cookie、コールバックqueryの除去、Secure/HttpOnly/SameSite Cookie。
- 投稿本文・投稿時刻の一覧・詳細表示。画像・動画のURL・バイト列の取得、Threads投稿の書き込み・削除なし。
- 取得済み本文だけを使うブラウザ内の固定ルールセルフチェック。追加API・外部送信・モデル呼出しなし。
- ログアウト、期限、認証解除callback、データ削除callbackによるメモリ内削除。
- callbackの署名検証、不正署名の拒否、確認コードと状況URLの応答。
- 合成Threads投稿によるブラウザE2EとAPIテスト。
- 公式問い合わせ先 `komekami7110@gmail.com` を4公開文書と審査資料に掲載し、公開ページでは `mailto:` リンクにする。

### 2026-11-12の外部確認

- 本番の `/`、`/privacy`、`/terms`、`/contact`、`/threads` は認証なしでHTTP 200。
- `/api/threads/config` は `live_enabled: true`、`mock_enabled: false`、`max_posts: 30`。
- 本番のAPIサービスとAPIコンテナは稼働中で、Threadsの本番モードは有効。CookieはSecure、セッション期限は30分、共有結果保存は無効、callback queryのログ除去も有効。
- FastAPIは `--no-access-log` で起動し、API/Webコンテナログは `json-file` の10MB×3ファイルで回転している。
- 本番APIコンテナからOllamaのtags APIへ接続できなかった。ホストにもOllamaプロセスはなく、GPUインスタンスは停止中。`live_enabled` はモデルの疎通確認ではないため、AI診断の稼働証明にはならない。
- OAuth、本人投稿取得、一覧・詳細表示、固定ルールセルフチェック、ログアウトはOllamaを呼ばない。今回の審査動画と審査手順はこのモデル非依存経路だけを使う。
- CloudFrontはHTTPS、地域制限はTerraform上 `none`。確認元からは公開ページへ到達できた。
- 変更前の `/data-deletion` と `/support` は404。本変更のデプロイ後に200を確認する必要がある。
- 別の外部取得サービスからCloudFront URLを取得できなかった。原因は特定できていないため、Meta審査員相当の別ネットワークから再確認する。

### 提出前のTODO（手動）

- [ ] この変更をレビューして本番へデプロイする（この作業ではデプロイしない）。
- [ ] デプロイ後、4公開URLがログインなしで200になり、モバイル幅でも読めることを確認する。
- [ ] Meta側のクローラまたは米国外を含む別ネットワークから4公開URLに到達できることを確認する。WAFのkill switchと `oauth-test-team-only` が無効であることもAWS Dashboardで読む。
- [ ] WAFのrequest samplingが本番でも無効、CloudFront標準access logが無効、FastAPIが `--no-access-log` であることを実環境で再確認する。
- [ ] 実テスターでOAuth→本人投稿取得→詳細表示→固定ルールセルフチェック→ログアウトを通し、コンテナログにcode、token、Cookie、投稿本文がないことを確認する。この通し確認が審査提出のブロッカー。
- [ ] 任意のAI診断を再提供するときは、GPUのvLLMを起動し、本番APIから `VLM_BASE_URL` に届くこと、`THREADS_TEXT_BACKEND=vlm`、本文・応答ログの扱いを確認する（Ollamaを選ぶ場合は `OLLAMA_BASE_URL` と `OLLAMA_MODEL`、アクセス制御も）。これは今回の `threads_basic` 審査提出のブロッカーではない。
- [ ] Meta DashboardのApp Icon、Category、App Domains、Privacy Policy、Terms、Data Deletion、Support、callback各URL、連絡先メール `komekami7110@gmail.com` を保存する。
- [ ] 審査員用Threadsアカウントと操作可能な認証情報を、Metaの安全な入力欄へ設定する。
- [ ] 上記チェックリストで英語字幕付きの本番動画を撮影し、`threads_basic` の申請へ添付する。
- [ ] 法務専門家による文面確認が必要なら、公開前に依頼する。

## AI処理の現在の提供状況

- 本番Ollamaへ接続できないため、任意のAI診断は現在利用できない。
- 画面ではAI診断を折りたたんだ任意機能として分離し、「モデル稼働時のみ」「Meta審査には不要」と表示する。
- 審査対象のOAuth、本人投稿取得、一覧・詳細表示、固定ルールセルフチェック、ログアウトはモデルを呼ばずに動く。
- 固定ルールセルフチェックをAI診断とは呼ばず、結果にも「AI診断ではない」と表示する。

## 審査時の利用可能性確認

本番反映後、提出直前に審査用アカウントで次を1回通し、すべて成功した場合だけ動画と申請を提出する。

1. `/threads` がログインなしで開く。
2. Threads OAuthから同じ `/threads` へ戻り、`@username` が表示される。
3. 「本人投稿を確認」で実投稿が2件以上表示される。
4. 「取得情報の詳細」と「公開情報をセルフチェック」がエラーなく動く。
5. 「ログアウト」で未接続状態へ戻り、同じCookieで `/api/threads/posts` が401になる。
6. 上記の間、アプリ・コンテナログに認可code、アクセストークン、Cookie、投稿本文が出ていない。

## 参考資料

- Meta公式Threads API Postman collection: <https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api>
- Meta Threads API changelog: <https://developers.facebook.com/docs/threads/changelog>
- リポジトリ内の認証・配備メモ: [threads-browser.md](threads-browser.md)
- API契約: [api-sse-contract.md](api-sse-contract.md)
