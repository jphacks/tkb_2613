# 現行 API・SSE 契約と担当境界

この文書は `main` の実装を記録する。実装前の企画書や AGENTS.md にある目標仕様とは区別し、ここにない機能は実装済みとして扱わない。

## 対象と共通動作

- api は FastAPI、画面からは同一オリジンの `/api` を使う。Next.js は `API_ORIGIN`（既定 `http://localhost:8001`）へ `/api/:path*` を中継する。
- api の応答は `Cache-Control: no-store, no-transform`（no-transform は、Next.js の中継が gzip で圧縮して SSE をためこむのを防ぐため）。SSE にはさらに `X-Accel-Buffering: no` が付き、イベント間が設定値 `SSE_KEEPALIVE_SECONDS`（既定15秒）以上空くと `: keep-alive` コメントが流れる。コメントは画面で読み飛ばす。
- セッション Cookie 名は `tkb_session`。値はランダムなセッションID。`AUTH_MODE=app_password` の Bluesky セッションは api プロセスのメモリ、`AUTH_MODE=oauth` のトークンは Next.js サーバーのメモリだけに置く。どちらも `SESSION_TTL_MINUTES`（既定30分）で失効する。api と Next.js は同じ環境変数を読む。アクセスでは延びない。
- `MOCK_MODE=1` が既定。モックログインは架空DIDを使い、Blueskyへ接続しない。モック診断は `eval/fixtures/demo_observations.json` を再生し、モデルにも接続しない。
- `MOCK_MODE=0` の診断では、セッションの DID の本人投稿だけを新しい順に最大 `MAX_POSTS` 件（既定30、設定上限100）取得する。

- 元に戻せない操作（`POST /api/delete`・`DELETE /api/session`・`POST`/`DELETE /api/result-link`）は、`Origin` ヘッダーが `CORS_ORIGINS` のどれかと同じ要求だけを受け付け、ほかは403「同じサイトから操作してください」（`Origin` がない要求も403）。Cookie の SameSite=Lax に加えた確認で、X・Threads の `/api/x/*`・`/api/threads/*` も同じ関数（`tkb_api.origin.check_origin`）でそれぞれの公開オリジンを確かめる。

## エンドポイント一覧

### OAuth 経路（`AUTH_MODE=oauth` の場合）

| メソッド・パス | 役割 |
| --- | --- |
| `POST /auth/start` | JSON `{"handle":"…"}` を受け取り、認可先URLを返す。SDK の PKCE・PAR・DPoP と、5分間の `tkb_oauth_start` HttpOnly Cookie を使う。 |
| `GET /auth/callback` | Cookie と SDK の state を照合し、本人 DID を確認して `tkb_session` を発行。コードと state のクエリを含まない `/` へリダイレクトする。 |
| `GET /oauth-client-metadata.json` | 公開クライアントのメタデータ。`atproto repo:app.bsky.feed.post?action=delete` の権限を公開する。 |
| `POST /__internal/oauth/complete` | Next.js からのみ使う。共有秘密のヘッダーがない場合は403。確認済み DID と handle で api セッションを作る。 |
| `POST /__internal/oauth/delete`・`drop` | api からのみ使う。共有秘密のヘッダーがない場合は403。削除前に api は診断済み・本人投稿を確認し、Next.js も DID と AT URI を再確認する。 |

OAuth 時の投稿取得は、セッション DID に限定して公開 AppView の `getAuthorFeed` を使う。Cookie と共有秘密を持つ内部経路は公開しない。ログアウト時は両プロセスのメモリからセッションを消す。Next.js は消す前に SDK の `revoke` で Bluesky 側のトークンを失効させる（失効に失敗してもメモリからは消し、ログアウトは204）。`SESSION_TTL_MINUTES` の期限が来たときも同じく失効させてから消す。

| メソッド・パス | リクエスト | 成功応答 | 実装上の注意 |
| --- | --- | --- | --- |
| `GET /health` | なし | `{"status":"ok","mock_mode":true}`（値は設定による） | 認証不要。生存確認用。 |
| `POST /api/session` | JSON `{"handle":"name.example","password":"…"}` | 200 `{"handle":"…","did":"did:…"}` と `tkb_session` Cookie | `AUTH_MODE=app_password` のみ。OAuth 時は404。`handle` はtrimし先頭の `@` を1つ除去。空handle/passwordは422。実ログイン失敗は401、Bluesky接続失敗は502、Bluesky の回数制限（429）は503 `bluesky_busy`。モック時は入力handleと固定DIDでログイン扱い。 |
| `GET /api/session` | `tkb_session` Cookie | 200 `{"handle":"…","did":"did:…"}` | Cookie欠落・無効・期限切れは401 `{"detail":"ログインしてください"}`。 |
| `DELETE /api/session` | `tkb_session` Cookie | 204、Cookie削除 | セッションがなくても204。 |
| `POST /api/detect` | 画像バイナリをリクエスト本文に直接送信。許可Content-Type: JPEG/PNG/WebP/HEIC/HEIF | モック時200 `{"clues":[…]}` | 空本文400、未対応形式415、20MiB超413。`MOCK_MODE=0` は現状501「検出はまだ実装されていません」。このルートはログイン必須ではない。 |
| `POST /api/diagnose` | `tkb_session` Cookie。任意JSON `{"public_web_lookup_consent":boolean}`（既定false） | `text/event-stream` | Cookieなし・無効は401。始められないときはストリームを始めずに理由のコードつきで断る（下の「理由のコードつきのエラー」）。成功時は以下のSSE順序。投稿/手がかり/診断結果はディスクやログに保存しない。投稿・手がかり・限定プロフィール推定・検索候補はログアウトまたは期限切れまでセッションのメモリだけに置き、次の診断開始時に置き換える。 |
| `GET /api/diagnosis` | `tkb_session` Cookie | 200 `{"posts":[Post],"clues":[Clue],"deleted":[post_id],"conclusions":[Conclusion],"plan":Plan,"profile_claims":[ProfileItem],"profile_claim_suggestions":[post_id],"external_profile_results":[ExternalProfileResult],"external_lookup_status":status,…}` | 同じセッションで完了済みの直近結果をモデル再解析なしで画面に復元する。`posts`・`clues` は診断時のまま（`clue_indices` の番号を変えない）。`deleted` は診断のあとに `POST /api/delete` で消せた投稿IDで、`conclusions` と `plan` はそれを除いて計算する（番号は `clues` での番号。`simulate` と同じ扱い）。Cookieなし・無効は401、結果がなければ404。結果はセッションとともに消える。 |
| `GET /api/features` | なし | 200 `{"share_enabled":true,"auth_mode":"app_password","public_web_lookup_available":true}` | 認証不要。`auth_mode` は `oauth` または `app_password`。`share_enabled` は設定 `SHARE_ENABLED`（既定1）。`public_web_lookup_available` は公開Web検索の同意欄を出せるかの真偽値だけで、`MOCK_MODE=1`（通信せず固定の架空候補を返す）か、`BRAVE_SEARCH_API_KEY` が空白以外のときに true。キーの値や長さは返さない。画面は true のときだけ同意欄を出し、読めなかったときは出さない。 |
| `POST /api/result-link` | `tkb_session` Cookie | 200 `{"token":"…"}` | 本人が画面で選んだとき、完了済みの結果を2時間の閲覧用スナップショットとして保存する。結果がなければ404。ランダムなトークンを URL のフラグメントに置き、アクセスログに記録しない。`SHARE_ENABLED=0` なら404 `share_disabled`（何も保存しない）。 |
| `DELETE /api/result-link` | `tkb_session` Cookie、JSON `{"token":"…"}` | 204 | 作成者の DID と一致するリンクだけを無効化する。別人のリンクは消せない。 |
| `POST /api/shared-result` | JSON `{"token":"…"}` | 200 `{"posts":[Post],"clues":[Clue],"conclusions":[Conclusion],"plan":Plan}` | トークンを知る人はログインなしで閲覧できる。無効・期限切れは404。閲覧側の画面に削除操作はない。結果は設定された `SHARE_DB_PATH` の SQLite に期限付きで保存し、APIプロセスの再起動後も読める。`SHARE_ENABLED=0` なら、オフにする前に作ったリンクも404 `share_disabled`。 |
| `GET /api/demo/diagnosis` | なし（Cookieを読まない） | 200 `{"demo":true,"posts":[Post],"clues":[Clue],"conclusions":[Conclusion],"plan":Plan}` | ログインなしの体験デモ。`DEMO_FIXTURE_PATH`（`eval/fixtures/demo_observations.json`）の架空アカウントだけを既存の推理にかける。`MOCK_MODE=0` でもモデル・Blueskyに接続しない。応答は起動時に一度だけ計算して使い回す（表のパスか地名の表が変われば計算し直す）。表が読めなければ503（起動は止めない）。画面は `/demo` で、「架空のアカウントです」を常に出す。 |
| `POST /api/demo/simulate` | なし。JSON `{"delete":["at://…",…]}`（最大100件） | 200 Simulation | 体験デモで投稿を仮に除いた結果。`after` の `clue_indices` は `GET /api/demo/diagnosis` の `clues` での番号。デモにない投稿ID・余計なキーは422（IDは応答に入れない）。削除のAPIはない。 |
| `POST /api/delete` | `tkb_session` Cookie。JSON `{"delete":["at://…",…]}` | 200 Deletion（下記） | 本人の投稿だけを Bluesky から1件ずつ消す。Cookieなし・無効は401、診断前は409、最後の診断にない投稿ID・もう消した投稿IDは422。消せた投稿IDはセッションの診断に記録し、2回目以降の `broken`・`after` はそれまでに消した投稿を除いた状態から計算する。途中で Bluesky に回数制限（429）で断られたら残りは試さず `failed` に入れ、`bluesky_busy: true` を返す。 |
| `POST /api/simulate` | `tkb_session` Cookie。JSON `{"delete":["at://…",…]}`（最大100件） | 200 Simulation（下記） | 実際には消さない（Bluesky の削除APIを呼ばない）。モデルも呼ばない。Cookieなし・無効は401、そのセッションで診断が終わっていなければ409、最後の診断にない投稿ID・もう消した投稿ID・余計なキーは422（送られたIDは応答に入れない）。もう消した投稿を除いた状態から計算する（`POST /api/delete` と同じ）。 |
| `POST /api/draft-check` | Cookie認証。JSON `{"text":"…","photo_base64":string|null,"photo_content_type":string|null}` | 200 `{"posts_checked":number,"overlaps":[…],"mock_mode":boolean,"notices":[…]}` | 認証必須。セッション本人の投稿だけを取得し、下書きと既存投稿の観測手がかりが一致する箇所を返す。診断の推理・投稿時刻由来推定は行わない。本文は最大10,000文字、写真は最大20MiB。 |

バリデーションエラーは422で `{"detail":[{"loc":[…],"msg":"…","type":"…"}]}` を返す。送信値そのものは詳細に含めない。その他のエラー形式は FastAPI のHTTPエラー応答に従う。

### 理由のコードつきのエラー

画面が理由ごとに文言を出し分けるエラーは `{"detail":{"code":"…","message":"…",…}}` の形で返す。画面は `code` で文言を選び（`web/src/lib/refusal.ts`、`web/src/lib/messages.ts`）、`message` は画面以外の呼び出し側のため。Python は `tkb_api.errors.refusal`。

| code | 状態 | 返すところ | ほかの項目 | 意味 |
| --- | --- | --- | --- | --- |
| `closed` | 503 | diagnose | `next_open`：次の公開の開始時刻（時差つき ISO 8601）。最後の公開の後は null | 公開時間外（`PUBLIC_WINDOWS`。空なら制限しない） |
| `already_running` | 409 | diagnose | — | 同じセッションか同じアカウント（DID）で診断中。別々にログインしても1アカウント1つまで |
| `daily_limit` | 429 | diagnose | `limit`、`resets_at`（日本時間の次の 0:00）。`Retry-After` ヘッダー | 1アカウント（DID）1日（日本時間）の回数の上限（`DIAGNOSE_DAILY_LIMIT`） |
| `busy` | 503 | diagnose | `retry_after`。`Retry-After` ヘッダー | 同時に診断できる数の上限（`MAX_CONCURRENT_DIAGNOSES`）。待たずに断る |
| `model_unavailable` | 503 | diagnose（`MOCK_MODE=0`） | — | 診断の前に VLM の `/models`、または `TEXT_BACKEND=ollama` で Ollama の `/api/tags` が応答せず指定モデルがない。OCR を使う設定で写真も読むときは、`GET {OCR_BASE_URL}/health` が 5xx か接続できない場合も（GPU の停止中・起動中）。回数は数えない |
| `bluesky_busy` | 503 | session、diagnose | — | Bluesky が回数制限（429）で断った |
| `share_disabled` | 404 | result-link（作成・無効化）、shared-result | — | 閲覧リンクの機能がオフ（`SHARE_ENABLED=0`）。保存先も作らない。作成と無効化は、ログインしていなければ先に401 |

- diagnose の確認の順：ログイン（401）→ 公開時間 → 同じセッション・同じアカウント → 1日の回数 → 同時実行の枠 → モデルの応答 → Bluesky からの投稿の取得。どれかで断ったときは、ストリームを始めない
- 1日の回数は、ストリームを始めるときに数える。公開時間外・混雑・モデルや Bluesky の不調で始められなかった分は数えない
- 同時実行の枠は、SSE の generator が終わる・途中で切れる・失敗するのどれでも返す。返し損ねても `DIAGNOSE_SLOT_TIMEOUT_SECONDS`（既定900秒）で空く
- 回数と枠はメモリだけに持つ（再起動で消える）。DID はプロセスごとのランダムな鍵で HMAC にして持つ
- 枠の期限 `DIAGNOSE_SLOT_TIMEOUT_SECONDS` は、最後に SSE を送った時刻（keep-alive を含む）から数える

## 共通データ型

Pythonの正は `common/src/tkb_common/schemas.py`、画面側の対応型は `web/src/types/`。

- **Post**: `post_id`（AT URI）、`text`、時差付き `created_at`、`images`。画像は `index, url, alt, width, height`。URLは `https://cdn.bsky.app/` のみ、画像は最大4枚。
- **Clue**: `post_id, image_index, type, value, region, confidence, source`。`region` は元画像ピクセルの `[x1,y1,x2,y2]` またはnull。本文由来は通常 `image_index/region=null`、`source=text`。画像alt由来は `source=alt` と画像の `image_index` を持ち、矩形はnull。プロフィール文由来の自己申告は `source=profile_text`。確信度は0〜1。許容type/sourceの列挙と写真/本文の整合条件は共通スキーマを参照。
- `TEXT_BACKEND=ollama` の本文手がかりには任意の `quote` が付く。これはモデルの出力を投稿本文の連続部分文字列として検証した原文引用で、`value` もその引用内の連続部分文字列に限定する。従来データは `quote=null` または省略可。既存の `post_id` とともに原文根拠を保持する。
- `TEXT_BACKEND` の既定は `vlm`。`ollama` では本文だけを Ollama に送る。`VLM_BASE_URL` が空なら画像を取得・抽出しない。設定されている場合は画像の従来VLM経路を使う。画像経路が失敗しても本文の成功結果を残す。
- `name_text` は人名として読めた文字に限る。誕生日の飾り文字や年齢の数字は抽出結果から除き、R8 の名前推定にも使わない。
- `Clue.type` に `local_item`（写真・本文）と `notice`（写真のみ）がある。写真の `code` は画像処理で解読し、`source=ocr` として返す。モデルが推測したバーコードの中身は住所の区画の根拠にしない。
- **DetectResponse**: `{"clues":[Clue,…]}`。
- **Simulation**: `{"delete":[投稿ID],"broken":[attribute],"after":[Conclusion]}`。`delete` の投稿を消したとして推理し直した結果。`broken` は、消す前に結論があり、消したあと1つもなくなる項目（値が別の値に変わっただけなら入れない）。`after` の `clue_indices` は、診断の `conclusions` イベントの `clues` での番号。Python は `tkb_api.pipeline.simulation_json`、TypeScript は `web/src/types/diagnose.ts` の `Simulation`。
- **Deletion**: Simulation ＋ `"failed":[投稿ID]` ＋ `"bluesky_busy":boolean`。`delete` は実際に消せた投稿だけで、`broken`・`after` はそれを除いて推理し直した結果（`clue_indices` は Simulation と同じく診断の `clues` での番号）。`failed` は消せなかった投稿。TypeScript は `web/src/types/diagnose.ts` の `Deletion`。
- **現在の診断Conclusion**: `rule, attribute, value, clue_indices, note, confidence`。`confidence` は0〜1で、根拠の手がかりの `confidence` を 1 − ∏(1 − c) で合成した値（`tkb_engine.rules.infer` が最後に入れる。同じ手がかりは2回数えない）。画面は数字を出さず、`STRONG_CONFIDENCE`（0.8）未満の推定にだけ「確からしさ：弱い」の印を付ける（0.8以上は印なし）。以前に保存した閲覧リンクにはこの欄がないので、TypeScript では省略可。`attribute` は試作の名前で、R1〜R12 は `home_city`・`home_district`・`station`・`home_area`・`home_block`・`active_time`・`routine`・`school`・`full_name`・`given_name_or_nickname`・`birthday`・`line`・`age`・`occupation` を返しうる。X1 は別投稿の生活圏・学校・家から通学する話を結び、`home_school_commute` を返す。これは経路や時刻の断定ではない。X2〜X5 も別々の投稿をつなぐ。X2 は R12 の `birthday` を年つきに置き換え、X3 は `long_term_home_absence`、X4 は `frequent_shop`、X5 は `workplace` を返す。R1 の `station` は、駅名の手がかりの票で選んだ駅のほかに候補が残ったとき、`note` に候補の駅の1日の乗降客数（国土数値情報の駅別乗降客数、出典つき）を「参考」として添える。どの駅を選ぶかには使わない。`clue_indices` は同じ `conclusions` イベントの `clues` 配列に対する0始まり番号。目標の16項目プロフィール型（status/confidence/evidence）とは別の試作型。
- 投稿時刻から R2 の行動時間・R3 の定期外出を出すには、投稿が3日以上に分かれている必要がある。R12 が投稿日を誕生日に使う際も同様。ただし年齢が明記された誕生日投稿では、その投稿の日を使う。デモを同日にまとめて投稿しただけで毎週の習慣を推定しない。

## 診断 SSE のイベント

SSEブロックは `event: <name>\ndata: <JSON>\n\n`。JSONはUTF-8で送られる。

| 順序 | event | data | 発生タイミング |
| --- | --- | --- | --- |
| 1 | `post` | `{"post": Post}` | 診断対象投稿をすべて取得した後、投稿一覧の順に全件送信。各投稿を送るたび手がかり抽出を待つわけではない。 |
| 2 | `clues` | `{"post_id":"…","clues":[Clue,…],"error":string|null}` | 抽出処理が完了した投稿ごと。抽出処理の完了順。成功時は `error:null`。投稿単位の抽出失敗時は空の `clues` とエラー文字列を送る。 |
| 3 | `conclusions` | `{"clues":[全Clue,…],"conclusions":[Conclusion,…],"profile_claims":[ProfileItem,…],"profile_claim_suggestions":[post_id,…],"web_facts":[WebFact,…],"web_lookup_status":status,"external_profile_results":[ExternalProfileResult,…],"external_lookup_status":status,"owner_profile_text":string,"self_report_clues":[Clue,…]}` | 全投稿の抽出処理の後に1回。`profile_claims` は限定ルールによる推定。`profile_claim_suggestions` は推定の根拠経路から選んだ最大3件。既存 `plan` イベントも続けて送る。 |
| 4 | `plan` | Simulation ＋ `"posts":[{"post_id","broken"},…]` | 推理の後に1回。`delete` は名前・生年月日・住まいなどの推定と、顔・名前・住所など直接写った手がかりを重みづけし、効果の大きい投稿から最大3件選ぶ（`tkb_engine.planner.plan`）。根拠だけ減って推定も重要な直接手がかりも残る候補は外す。`posts` は各投稿だけを消したときに崩れる項目で、顔の写真だけを消す候補などでは空になりうる。候補がなければ `delete` は空。 |
| 5 | `done` | `{"posts_seen":number}` | 正常完了時に1回。 |

### 失敗・切断の現状

- 投稿単位の抽出失敗は `clues.error` に載る。現行パイプラインはその後も残りの処理を続け、集まった手がかりで `conclusions`、続けて `done` を送る。したがって `done` は全投稿の抽出成功を意味しない。
- `post`、抽出器の準備、Bluesky投稿取得など診断全体の失敗は、ストリーム開始前なら通常のHTTPエラー（例: 401/502/503）。ストリーム開始後に起きた例外を表す専用 `error` SSE イベントは現行実装・型にない。接続が途中終了すれば画面側は `done` 不達として「診断の途中で接続が切れました」とエラー表示する。
- クライアントは未知のイベント名を無視し、既知イベントの不正な形は不正応答として扱う。`done` 前の正常なEOFも切断エラー。
- 再実行開始時、画面は前回の投稿・手がかり・結論をクリアする。画面離脱時は AbortController で通信を中断する。
- SSEのイベント順序や部分失敗時の画面表現をさらに整える作業は Issue #46 の範囲。

### プロフィール推定と公開Web検索

- 現在の限定推論対象は `residential_area`, `regular_station`, `employer_name`, `child_age`。候補は本人の複数投稿・観測手がかり・本人プロフィール文の組合せから作る。成立条件、棄却条件、根拠経路、確信度の扱いは [profile-classification-v2.md](profile-classification-v2.md) を参照。
- 根拠（`ProfileEvidence`）の `source` は `clue` / `post_text` / `profile_text` / `image_alt` / `public_web` / `open_data`。`open_data` は事前に取得した公的な公開データ（手元の表）を「X は Y」という一般的な知識として使った根拠で、`excerpt` に出典と注記だけを入れ、`post_id`・`clue_index`・`image_index`・`web_fact_id` は null。診断のたびに外部へ問い合わせない。画面は推定の下に `excerpt` をそのまま出す。現在は `residential_area` の避難所の経路（「自宅近くの X」の投稿と、別の投稿の手がかりに出てくる X、国土地理院の避難所の表で X が1つの区市町村だけにあること）で使い、`excerpt` に「最新でない場合や未掲載の場合があります」という国土地理院の注記を必ず入れる。`residential_area` には、国土数値情報のバス停留所（令和4年度版）の経路もある（「家の前のバス停、X」「毎朝 X バス停からバスに乗る」などと、別の投稿の手がかりの X。同じ名前のバス停が多いので、事業者名か区市町村名で1つの区市町村に絞れたときだけ）。`excerpt` に整備時点（令和4年度）と「今と違う場合があります」を入れる。子どもの学校の推定（`child_school`）が出ているときは、国土数値情報の小学校区・中学校区で、その学校の学区の区市町村を `residential_area` の経路に足す（同名の学校が2つ以上の区市町村にあれば足さない）。`child_school` は、本人の子どもの学校の X（「娘の小学校のひまわり祭り」）と、別の投稿の「X は〇〇小学校」（本文の手がかり `org_text` が同じ学校名）が同じ X でつながり、学区の表で学校が1つの区市町村にだけあるときに推定する（`docs/profile-classification-v2.md`）。`employer_name` では、本人が勤務先として明示した名前（「勤務先は X」「X で働いてる」など）と、別の投稿に書かれた同じ名前を、国税庁の法人番号の表で正式名称に結ぶ経路で使う（正規化した名前が1つの法人にだけ一致するとき。部分一致はしない）。この経路が成り立つと、公開Webの `WebFact` の経路の代わりになる。`excerpt` には出典と表の時点を入れ、法人番号と本店所在地は入れない。
- `profile_claim_suggestions` は推定の根拠経路がすべて崩れる投稿の組合せから最大3件を選ぶ。これは main の Conclusion 向け `plan` / `/api/simulate` と別の根拠モデルで、実削除はしない。
- 公開Web検索は診断ごとの明示同意がある場合だけ行う。送信値は本人の公開Blueskyハンドルと固定 `site:` 検索演算子のみ。投稿文・プロフィール文・Clue・DID・投稿URI・画像・氏名は送らない。Brave検索語は最大90日保持され、実検索は `BRAVE_SEARCH_API_KEY` 設定時のみ可能。検索の費用は運営が負担し、利用者には請求しない。実モードでキーがないのに `public_web_lookup_consent: true` が送られた場合は Brave に何も送らず、`external_lookup_status` を `unavailable`、`external_profile_results` を空にする（診断そのものは続ける）。
- `external_profile_results` は検索候補と、本人プロフィール/投稿に記載されたURLと照合した候補を返す。これは公開URL上のリンク関係を示すだけで、実世界の本人確認や記事の執筆者確認を意味しない。検索結果本文の取得はしない。`MOCK_MODE=1` は固定fixtureのみで外部通信しない。
- `GET /api/diagnosis` による復元用データは既存の投稿・手がかり・planに加え、profile claims・候補・同意後の外部検索結果と状態・プロフィール文・自己申告手がかりを含む。いずれもプロセス内セッションメモリのみで保持し、Cookieの期限・ログアウト・次の診断で消える。共有リンクの形式は別途定義されているため、共有応答にこの追加データは含めない。

## 担当境界とデータ受け渡し

担当記号はIssueの記述にあるA/B/C/Dを使い、個人名やIssueにない合意内容は補わない。

| 担当 | 現在の責務・境界 | 主な受け渡し |
| --- | --- | --- |
| A | Web画面・操作・結果表示。APIとの通信、型検証、診断中の状態表示を担当。 | `web/src/types` の `Post`, `Clue`, `DiagnoseEvent`, `SessionResponse` と `web/src/lib/api.ts` を介してJSON/SSEを受け取る。Aの仮除外比較画面はIssue #69。 |
| B | 投稿単位の写真/本文から観測手がかりを抽出する担当範囲（Issue #60）。現行 `detect/` は抽出器・OCR/VLMクライアントを持つ。 | 入力は`Post`と画像bytes、出力は `PostExtraction(post_id, clues: Clue[])`。api pipelineが受け取りSSE `clues` と `conclusions.clues` へ渡す。独立 `POST /api/detect` の本番処理は未実装。 |
| C | 手がかりからの推理ルール、プロフィール推定・削除前後計算の担当範囲（Issue #59/#61/#65）。 | 入力は `Clue[]`、`Post[]`、必要な地名辞書。現行 `engine` の `infer` は試作 `Conclusion[]` を返し、`clue_indices` で入力Clueを参照。`planner` の `plan`・`simulate` は `infer` をかけ直して Simulation を返す（PR #77）。共通16項目型は未接続。 |
| D | API、Bluesky本人セッション/投稿取得、診断パイプライン、各担当間の統合（Issue #38/#40/#45/#48）。 | Cookie付きHTTPを受け、`Post[]`→Bの抽出→`Clue[]`→Cの推理→SSEイベントとしてAへ渡す。`plan` イベントと `POST /api/simulate`（Issue #48 の最小版）で、Cの `tkb_engine.planner` を画面へ渡す。 |

**依存の流れ:** A ⇄ D(API/SSE) → B(抽出) → D(集約) → C(推理) → D(SSE) → A(表示)。型の共有元はPythonでは`common/`、TypeScriptでは`web/src/types/`。API固有のログイン要求/応答は `api/src/tkb_api/schemas.py` と `web/src/types/session.ts` で対応する。

## まだ実装されていない目標機能

- 16項目プロフィールの `found/weak/unknown`、確からしさ、根拠を含む共通出力（現行は試作Conclusion）。
- 16項目プロフィールでの削除候補・仮除外（現行の planner と simulate は試作Conclusionを対象にする）。
- Blueskyログイン時以外の本番画像/本文抽出の統合完了確認。独立detectエンドポイントはモックのみで、本番は501。
- SSEの全体失敗イベント、途中切断後の再開・再送プロトコル。

これらはAGENTS.mdの目標やIssueの後続範囲であり、この文書の現行契約には含めない。

## X 専用の公開情報チェック

Bluesky の `/api/session`・`/api/diagnose`・`/api/simulate`、Threadsの診断とは独立した `/api/x/*`。X の OAuth と結果は専用の HttpOnly `x_tkb_session` Cookie（Path `/api/x`）を使う。X の実投稿は用途承認・費用承認・上流クエリログ対策がそろうまで拒否する。本文にそのまま現れる地名・駅名・曜日・時刻・学校名だけをX専用の決定的な抽出器で集計し、既存のプロフィール推定・外部モデル・外部検索は呼ばない。結果はプロセスメモリだけに置き、実投稿の変更・削除・結果共有は行わない。

`information` の1項目は `{"category":"station","value":"渋谷駅","count":2,"evidence":[{"post_id":"x:9001","quote":"渋谷駅"}, ...]}`。`category` は `place | station | weekday | time | school`。`quote` は必ず該当投稿本文の部分文字列で、`count` は同じ値を明記した投稿数（同一投稿内の反復は1件）とする。

| メソッド・パス | 入力 | 応答・動作 |
| --- | --- | --- |
| `GET /api/x/config` | なし | `mock_enabled, live_enabled, max_posts, info_view`。秘密設定は返さない。 |
| `POST /api/x/mock/session` | `{"consent":true}` | `X_MOCK_MODE=1` のときだけ架空アカウントのセッションを発行。 |
| `POST /api/x/start` | `{"consent":true}` | 用途・費用承認が有効なときだけ PKCE S256 の `authorize_url` と開始 Cookie を返す。その日（UTC）の `X_DAILY_RESOURCE_LIMIT` に本人確認＋1回の投稿取得の分が残っていなければ429（`Retry-After`）。 |
| `GET /api/x/callback` | X の `state,code` と開始 Cookie | state/PKCE を照合し、トークン交換と本人確認の後 `/x` へ 303。本人確認の前に1日の上限から1を予約し、足りなければ429。 |
| `GET /api/x/session` | X セッション Cookie | `username, mock`。未認証401。 |
| `DELETE /api/x/session` | X セッション Cookie | セッション・結果をメモリから削除、204。 |
| `POST /api/x/diagnose` | X セッション Cookie | `posts, view, information, post_errors, x_display, elapsed_ms, mock`。`view` は `X_INFO_VIEW`（`aggregate` 既定／`highlight`）。`highlight` のときは `information` を空にし、`highlights: {<post_id>: [{category: station|place, start, end}]}`（コードポイント単位）を返す。`x_display` は X の表示要件用の `{synthetic, author:{username,name,profile_image_url,profile_url}, posts:{<post_id>:{permalink,edited,entities:[{kind,start,end,href,display}]}}}`。`start`・`end` はコードポイント単位。合成デモは `synthetic=true` で `profile_url`・`permalink` は null、`entities` は空。`post_errors` は読み取りに失敗した投稿の `{post_id, error}` で、`error` は固定文言（本文を含めない）。1件の失敗で全体は失敗にしない。実経路は本人投稿を最大30リソース読み、限定カテゴリだけをローカルで集計する。2回目はメモリの結果を返し再課金しない。投稿取得の前に `max(5, X_MAX_POSTS)` を1日の上限から予約し、足りなければ X を呼ばずに429。 |
| `GET /api/x/diagnosis` | X セッション Cookie | 直近の完了結果。なければ404。 |
| `POST /api/x/simulate` | `{"delete":[診断済み投稿ID]}` | `delete, before, after, removed`。X APIは再呼出ししない。`view=highlight` で診断したセッションでは件数の比較を作らず409。 |
| `POST /api/x/rediagnose` | 同上 | 除外後の `posts, view, information（highlight では空と highlights）, post_errors, mock` を作り直す。X APIは再呼出ししない。 |

X の状態変更 API は同一オリジンの `Origin` ヘッダーを要求する。投稿IDは `x:<numeric id>`、画像は空配列。429は503と `Retry-After` を返す。詳細な設定・規約・費用は [x-poc.md](x-poc.md)。

### Threads 読み取り専用経路（実認証は既定無効）

`/api/threads/config`、`/start`、`/callback`、`/session`、`/posts`、`/diagnose`、`/diagnosis`、`/simulate`、`/rediagnose`、`/mock/session` は専用 Cookie とメモリ内セッションを使う。`GET /posts` は `{"posts":[Post],"mock":false}` を返し、診断モデルが未稼働でも本人投稿の取得を確認できる。画面はこの応答を一覧・詳細表示し、取得済み本文だけをブラウザ内の固定パターンで確認する「AIを使わない公開情報セルフチェック」を提供する。このチェックは追加APIやモデルを呼ばず、所有者・実在性・意味を推定しない。取得元の Threads ID がセッションの本人 ID と異なれば502で拒否する。取得した投稿はセッションのメモリに保持し、続く任意のAI診断で再利用する。Threads APIには投稿ID・本文・日時・メディア種別を要求するが、共通`Post`型へ保持するのは投稿ID・本文・日時だけで、画像・動画のURLやバイト列は取得しない。投稿 ID は `threads:` で始まる。実削除には対応しない。操作 API は同一 Origin を要求する。OAuth は `threads_basic` のみで、HTTPS callback、短命 Cookie と一回限りの state、本人 ID の照合を使う。callback の成功は `/threads`、失敗はコードと state を除いた `/threads?auth_error=...` に303で戻す。期限は最大30分で、期限・ログアウト時に結果とトークンを破棄する。実認証には `THREADS_ENABLED`、`THREADS_QUERY_LOGS_REDACTED`、安全な Cookie、`THREADS_APP_ID`・`THREADS_APP_SECRET` が必要。任意のAI診断は現状ローカル Ollama を使い、モデル停止中は利用できないが、OAuth・本人投稿取得・一覧／詳細・固定ルールチェック・ログアウトには影響しない。実環境の経路のログ保護と Meta 側設定の確認は別途必要。

Meta の管理画面に登録する解除・削除依頼用 URL はそれぞれ `POST /api/threads/deauthorize` と `POST /api/threads/data-deletion`。両方とも `signed_request` を Threads App Secret の HMAC-SHA256 で検証し、対象 Threads ID の全セッションを消す。署名不正は400。削除依頼は `url`（`/threads/data-deletion-status`）とランダムな `confirmation_code` を返す。これらは OAuth コールバックとは別の経路であり、Cookie や Origin ヘッダーを要求しない。
