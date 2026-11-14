# 現行 API・SSE 契約と担当境界

この文書は `main` の実装を記録する。実装前の企画書や AGENTS.md にある目標仕様とは区別し、ここにない機能は実装済みとして扱わない。

## 対象と共通動作

- api は FastAPI、画面からは同一オリジンの `/api` を使う。Next.js は `API_ORIGIN`（既定 `http://localhost:8001`）へ `/api/:path*` を中継する。
- api の応答は `Cache-Control: no-store, no-transform`（no-transform は、Next.js の中継が gzip で圧縮して SSE をためこむのを防ぐため）。SSE にはさらに `X-Accel-Buffering: no` が付き、イベント間が設定値 `SSE_KEEPALIVE_SECONDS`（既定15秒）以上空くと `: keep-alive` コメントが流れる。コメントは画面で読み飛ばす。
- セッション Cookie 名は `tkb_session`。値はランダムなセッションID。`AUTH_MODE=app_password` の Bluesky セッションは api プロセスのメモリ、`AUTH_MODE=oauth` のトークンは Next.js サーバーのメモリだけに置く。どちらも `SESSION_TTL_MINUTES`（既定30分）で失効する。api と Next.js は同じ環境変数を読む。アクセスでは延びない。
- `MOCK_MODE=1` が既定。モックログインは架空DIDを使い、Blueskyへ接続しない。モック診断は `eval/fixtures/demo_observations.json` を再生し、モデルにも接続しない。
- `MOCK_MODE=0` の診断では、セッションの DID の本人投稿だけを新しい順に最大 `MAX_POSTS` 件（既定30、設定上限100）取得する。

## エンドポイント一覧

### OAuth 経路（`AUTH_MODE=oauth` の場合）

| メソッド・パス | 役割 |
| --- | --- |
| `POST /auth/start` | JSON `{"handle":"…"}` を受け取り、認可先URLを返す。SDK の PKCE・PAR・DPoP と、5分間の `tkb_oauth_start` HttpOnly Cookie を使う。 |
| `GET /auth/callback` | Cookie と SDK の state を照合し、本人 DID を確認して `tkb_session` を発行。コードと state のクエリを含まない `/` へリダイレクトする。 |
| `GET /oauth-client-metadata.json` | 公開クライアントのメタデータ。`atproto repo:app.bsky.feed.post?action=delete` の権限を公開する。 |
| `POST /__internal/oauth/complete` | Next.js からのみ使う。共有秘密のヘッダーがない場合は403。確認済み DID と handle で api セッションを作る。 |
| `POST /__internal/oauth/delete`・`drop` | api からのみ使う。共有秘密のヘッダーがない場合は403。削除前に api は診断済み・本人投稿を確認し、Next.js も DID と AT URI を再確認する。 |

OAuth 時の投稿取得は、セッション DID に限定して公開 AppView の `getAuthorFeed` を使う。Cookie と共有秘密を持つ内部経路は公開しない。ログアウト時は両プロセスのメモリからセッションを消す。

| メソッド・パス | リクエスト | 成功応答 | 実装上の注意 |
| --- | --- | --- | --- |
| `GET /health` | なし | `{"status":"ok","mock_mode":true}`（値は設定による） | 認証不要。生存確認用。 |
| `GET /api/mock-assets/{asset_name}` | ファイル名 | 200 画像バイナリ | `MOCK_MODE=1` かつ `MOCK_LOCAL_ASSETS_ENABLED=1` のときだけ、fixtureで参照されるファイルを同じディレクトリの `images/` から配信する。既定では無効。ファイル名のみ許可し、拡張子を画像形式に限定する。実モードでは404。キャッシュしない。 |
| `POST /api/session` | JSON `{"handle":"name.example","password":"…"}` | 200 `{"handle":"…","did":"did:…"}` と `tkb_session` Cookie | `AUTH_MODE=app_password` のみ。OAuth 時は404。`handle` はtrimし先頭の `@` を1つ除去。空handle/passwordは422。実ログイン失敗は401、Bluesky接続失敗は502、Bluesky の回数制限（429）は503 `bluesky_busy`。モック時は入力handleと固定DIDでログイン扱い。 |
| `GET /api/session` | `tkb_session` Cookie | 200 `{"handle":"…","did":"did:…"}` | Cookie欠落・無効・期限切れは401 `{"detail":"ログインしてください"}`。 |
| `DELETE /api/session` | `tkb_session` Cookie | 204、Cookie削除 | セッションがなくても204。 |
| `POST /api/detect` | 画像バイナリをリクエスト本文に直接送信。許可Content-Type: JPEG/PNG/WebP/HEIC/HEIF | モック時200 `{"clues":[…]}` | 空本文400、未対応形式415、20MiB超413。`MOCK_MODE=0` は現状501「検出はまだ実装されていません」。このルートはログイン必須ではない。 |
| `POST /api/diagnose` | `tkb_session` Cookie。任意JSON `{"public_web_lookup_consent":boolean,"photo_place_web_lookup_consent":boolean,"photo_place_reference_consent":boolean}`（3つとも既定false） | `text/event-stream` | Cookieなし・無効は401。3つの同意は別用途で相互に代替しない。Commonsへ送る前に日本国内の座標と全国1kmメッシュ所属、ローカルPOIの名称一致、非住居カテゴリ、source licenseを再検査する。始められないときはストリームを始めずに理由のコードつきで断る（下の「理由のコードつきのエラー」）。成功時は以下のSSE順序。投稿/手がかり/診断結果はディスクやログに保存しない。投稿・手がかり・限定プロフィール推定・検索候補はログアウトまたは期限切れまでセッションのメモリだけに置き、次の診断開始時に置き換える。 |
| `GET /api/diagnosis` | `tkb_session` Cookie | 200 `{"posts":[Post],"clues":[Clue],"deleted":[post_id],"photo_place_results":[PhotoPlaceResult],"plan":Plan,"profile_claims":[ProfileCandidateSet;29],"profile_relations":[ProfileRelation],"profile_claim_suggestions":[post_id],"web_facts":[WebFact],"external_profile_results":[ExternalProfileResult],…}` | 同じセッションで完了済みの直近結果をモデル再解析なしで画面に復元する。公開レスポンスに旧 `conclusions` は含めない。Cookieなし・無効は401、結果がなければ404。結果はセッションとともに消える。写真場所結果は診断時に得た観測で、投稿を消した場合は表示から除く。 |
| `GET /api/features` | なし | 200 `{"share_enabled":true,"auth_mode":"app_password","public_web_lookup_available":false,"photo_place_web_lookup_available":false,"commons_reference_lookup_available":false}` | 認証不要。`auth_mode` は `oauth` または `app_password`。`share_enabled` は設定 `SHARE_ENABLED`（既定1）。公開Web検索フラグはそれぞれ独立。Brave写真場所検索は `MOCK_MODE=0`、Braveキーあり、かつ `DIAGNOSE_DAILY_LIMIT > 0` の場合のみtrue。Commons参照照合は `COMMONS_REFERENCE_LOOKUP_ENABLED=1`、実モード、有限の日次診断上限と、共通resolverで選ばれる読み取り可能・対応schema versionの`places.sqlite3`と選択ディレクトリの`muni_mesh.parquet`をすべて満たす場合のみtrue。resolverは選択ディレクトリを優先し、`data/processed/national`の場合だけ`data/processed/places.sqlite3`へfallbackする。 |
| `POST /api/result-link` | `tkb_session` Cookie | 200 `{"token":"…"}` | 本人が画面で選んだとき、完了済みの結果を2時間の閲覧用スナップショットとして保存する。結果がなければ404。ランダムなトークンを URL のフラグメントに置き、アクセスログに記録しない。`SHARE_ENABLED=0` なら404 `share_disabled`（何も保存しない）。 |
| `DELETE /api/result-link` | `tkb_session` Cookie、JSON `{"token":"…"}` | 204 | 作成者の DID と一致するリンクだけを無効化する。別人のリンクは消せない。 |
| `POST /api/shared-result` | JSON `{"token":"…"}` | 200 新規snapshotは `{"posts":[Post],"clues":[Clue],"plan":Plan,"profile_claims":[ProfileCandidateSet;29],"profile_relations":[ProfileRelation],…}` | トークンを知る人はログインなしで閲覧できる。新形式は候補セット中心で、保存済みの値を表示し推論を再実行しない。旧形式の保存済みリンクはTTL中、保存されたConclusionを読み取り専用で表示する。無効・期限切れは404。閲覧側の画面に削除操作はない。結果は設定された `SHARE_DB_PATH` の SQLite に期限付きで保存し、APIプロセスの再起動後も読める。`SHARE_ENABLED=0` なら、オフにする前に作ったリンクも404 `share_disabled`。 |
| `POST /api/delete` | `tkb_session` Cookie。JSON `{"delete":["at://…",…]}` | 200 Deletion（下記） | 本人の投稿だけを Bluesky から1件ずつ消す。Cookieなし・無効は401、診断前は409、最後の診断にない投稿IDは422。途中で Bluesky に回数制限（429）で断られたら残りは試さず `failed` に入れ、`bluesky_busy: true` を返す。 |
| `POST /api/simulate` | `tkb_session` Cookie。JSON `{"delete":["at://…",…]}`（最大100件） | 200 Simulation（下記） | 実際には消さない（Bluesky の削除APIを呼ばない）。モデルも呼ばない。Cookieなし・無効は401、そのセッションで診断が終わっていなければ409、最後の診断にない投稿IDや余計なキーは422（送られたIDは応答に入れない）。 |
| `POST /api/draft-check` | Cookie認証。JSON `{"text":"…","photo_base64":string|null,"photo_content_type":string|null}` | 200 `{"posts_checked":number,"overlaps":[…],"mock_mode":boolean,"notices":[…]}` | 認証必須。セッション本人の投稿だけを取得し、下書きと既存投稿の観測手がかりが一致する箇所を返す。診断の推理・投稿時刻由来推定は行わない。本文は最大10,000文字、写真は最大20MiB。 |

バリデーションエラーは422で `{"detail":[{"loc":[…],"msg":"…","type":"…"}]}` を返す。送信値そのものは詳細に含めない。その他のエラー形式は FastAPI のHTTPエラー応答に従う。

`GET /api/diagnosis` は、診断時の `posts` と `clues` を保持したまま、実際に消せた投稿IDを `deleted` に返す。投稿・手がかりの元配列順と `clue_indices` は変えない。`plan`、29件のプロフィール候補セット、関係、候補投稿IDは `deleted` を反映して返す。公開レスポンスには旧 `conclusions` を含めない。内部のR/X/BPルール中間値は候補セット生成にだけ使う。`photo_place_results` は診断時の画像ごとの観測であり、snapshot復元/削除時には場所推論や外部APIを再実行しない。ローカル許諾済みPOIと本人の明示的な家周辺文脈、別投稿の独立した同地域根拠がそろった `residential_area` 経路は `profile_claims` の保存済みcandidate_poolに含まれ、写真投稿または地域根拠投稿のどちらかが削除・仮除外されると必須根拠の経路が再評価で落ちる。削除投稿の `photo_place_results` は画面から除く。プロフィール候補セットは保存済みの全 `candidate_pool` と残存する投稿・手がかりから再評価し、推論器や外部APIは呼ばない。診断開始時刻 `diagnosis_at` はセッション内の診断状態に保持し、現在地など時間で鮮度が変わる候補はその時刻で評価する。削除済みIDは候補提案から除く。フロントエンドは削除済み投稿を一覧・画像表示・削除候補・表示中のプラン要約から除外し、仮除外中も候補と根拠から除く。診断結果はセッションTTL（既定30分）、ログアウト、次の診断開始で破棄される。

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

- **Post**: `post_id`（AT URI）、`text`、時差付き `created_at`、`images`。画像は `index, url, alt, width, height` と任意の `mock_asset`。通常の `url` は `https://cdn.bsky.app/` のみ、画像は最大4枚。`mock_asset` はローカルfixture画像のファイル名で、モック画面表示だけに使う。実モードの画像取得は従来どおりCDN URLだけを使う。
- **Clue**: `post_id, image_index, type, value, region, confidence, source`。`region` は元画像ピクセルの `[x1,y1,x2,y2]` またはnull。本文由来は通常 `image_index/region=null`、`source=text`。画像alt由来は `source=alt` と画像の `image_index` を持ち、矩形はnull。プロフィール文由来の自己申告は `source=profile_text`。確信度は0〜1。許容type/sourceの列挙と写真/本文の整合条件は共通スキーマを参照。
- **PhotoPlaceResult**: `post_id,image_index,status,granularity,candidates,reason_codes,lookup_status`。`lookup_status` は `local_only | web_searched | reference_checked | unavailable`。候補は `place_id,label,place_type,photo_relation,area_label,score,evidence,source_ids,sources,corroborated_by`、出典には `provider,dataset,license_id,record_id,version,attribution,source_url` を保持する。外部Brave結果では一時IDをrecord_id等へ保存せず、公開HTTPSのsource_urlだけを表示用に保持する。候補のclue evidenceは同じ画像の clue index を参照する。`visible_in_frame` は対象物が画像に写ることだけを表し、カメラの撮影地点や本人の現在地・居住地を示さない。任意のローカルPOI SQLite索引がない/手がかり不足なら `unknown`、同名IDが複数なら `ambiguous`。索引の `user_version` が非対応の場合は検索せず、対象手がかりに `poi_index_schema_mismatch` を付けて `unknown` にする。一意名の取得は最大50件で、超過時は `reason_codes` に `too_many_matches` を付け候補省略を明示する。候補は未確認の観測候補で、名称一致だけで所在地を検証済みにしない。Brave候補も未確認の `visible_in_frame` に限り、画像・住所・検索語以外の手がかりを根拠として扱わない。`corroborated_by`（既定 `[]`、最大1件、古いsnapshotでは省略可）は、Brave候補の名称（正規化後）・`addressRegion`（都道府県）・`addressLocality`（市区町村、完全一致）が、同じ結果内の公的データセット（現行は国土数値情報 `P05-22` のみ。都道府県は `record_id` の行政区域コードから取る）のローカル候補ちょうど1件と一致したときだけ、その `place_id` を入れる。参照先は同じ結果内の別候補でなければならず、Python/TypeScriptとも参照切れ・自己参照を拒否する。裏付けは表示用で、`status`・`score`・`photo_relation`・`lookup_status` と `residential_area` などの推論入力を変えない。都道府県または市区町村が欠ける、末尾だけの一致（「北区」など）、同じ市区町村に同名の公的記録が複数、民間・集合データ（Overture等）のみの場合は付けない。PhotoPlaceResult単独ではprofile claimを生成しない。`residential_area`への保守的経路は、`LOCAL_ONLY`/`REFERENCE_CHECKED`/`UNAVAILABLE`でも保持されたライセンス付きローカル施設候補に限定し、写真本文の明示的な家周辺表現が候補名と一致し、同じ候補名が画像Clue.valueとも正規化一致し、粗いarea_labelと別投稿の同地域PLACE_TEXT/近隣・日常文脈がそろった場合だけ弱い候補を作る。`WEB_SEARCHED`候補は使わない。`score` は未校正なので画面には百分率や数値を表示しない。Commons参照証拠は別同意後、一意座標付きのライセンス済みローカル候補だけを種にし、GeoDataの座標照会と許可license（CC0 1.0 / CC BY 3.0 / CC BY 4.0）の作者・license・file pageを確認できたthumbnailを使う。1診断最大3座標候補・3枚、thumbnail各512KiB、Commons API request合計6回まで。本人の写真はcdn.bsky.appから必要な1枚だけ4MiB上限で再取得し、比較用byteと特徴はメモリ内で破棄する。Commonsへ本人画像・本文・DID・投稿IDは送らない。reference evidenceはpHash距離2bit以下かつSSIM 0.985以上、同じaspect ratio、低texture画像でない場合だけ付ける。画像取得だけではevidenceを付けず、status/score/photo_relationを変えず、camera_*やprofile claimを導かない。一般的な別角度照合は未実装。
- **ProfileEvidence.source**: `clue`, `post_text`, `profile_text`, `image_alt`, `public_web`, `open_data`。`public_web` 根拠は投稿IDを持たず `web_fact_id` を参照する。`open_data` 根拠も投稿IDとclue indexを持たず、出典表示に使う非空の `excerpt` を持つ。
- `TEXT_BACKEND=ollama` の本文手がかりには任意の `quote` が付く。これはモデルの出力を投稿本文の連続部分文字列として検証した原文引用で、`value` もその引用内の連続部分文字列に限定する。従来データは `quote=null` または省略可。既存の `post_id` とともに原文根拠を保持する。
- `TEXT_BACKEND` の既定は `vlm`。`ollama` では本文だけを Ollama に送る。`VLM_BASE_URL` が空なら画像を取得・抽出しない。設定されている場合は画像の従来VLM経路を使う。画像経路が失敗しても本文の成功結果を残す。
- `name_text` は人名として読めた文字に限る。誕生日の飾り文字や年齢の数字は抽出結果から除き、R8 の名前推定にも使わない。
- `Clue.type` に `local_item`（写真・本文）、`notice`（写真のみ）、`vehicle_model`（写真・本文の観測）がある。`vehicle_model` は車種名・ロゴなどの観測で、推定には本人の自家用車だと示す本文と車種の文字一致を別途必要とする。写真の `code` は画像処理で解読し、`source=ocr` として返す。モデルが推測したバーコードの中身は住所の区画の根拠にしない。 BCBP（搭乗券バーコード）は `common/src/tkb_common/bcbp.py` で解析し、予約番号PNRは clueを返す前に `*` でマスクする。
- **DetectResponse**: `{"clues":[Clue,…]}`。
- **Simulation**: `{"delete":[投稿ID],"broken":[attribute],"after":[ProfileCandidateSet;29]}`（Threads `/api/threads/simulate` は互換のため `after:[Conclusion]`）。`delete` の投稿を消したとして29項目候補セットを再評価した結果。`broken` は、消す前に候補（`candidates` 非空）があり、消したあと候補が1つもなくなる `ProfileAttribute`（順位変更だけなら入れない）。Python は `tkb_api.pipeline.simulate_claims_json`（互換用 `simulation_json` は Threads 等向け）、TypeScript は `web/src/types/diagnose.ts` の `Simulation`。
- **Deletion**: Simulation ＋ `"failed":[投稿ID]` ＋ `"bluesky_busy":boolean`。`delete` は実際に消せた投稿だけで、`broken`・`after` はそれを除いて29項目候補セットを再評価した結果。`failed` は消せなかった投稿。TypeScript は `web/src/types/diagnose.ts` の `Deletion`。
- **内部ルール中間値 `Conclusion`**: engine のR/X/BP推理とThreads互換レスポンス向けの型。BlueskyのSSEと診断snapshotでは公開せず、29件の `ProfileCandidateSet` を唯一のプロフィール結果とする。Threads route は旧形式を必要とするため独立した互換処理を持つ。R1〜R12、X1〜X5、BP1/BP2が生成し、搭乗券BP1の氏名は旅客名であって投稿者本人と未確認のため、本人名の確定値ではなく推定候補として表示する。
- 投稿時刻から R2 の行動時間・R3 の定期外出を出すには、投稿が3日以上に分かれている必要がある。R12 が投稿日を誕生日に使う際も同様。ただし年齢が明記された誕生日投稿では、その投稿の日を使う。デモを同日にまとめて投稿しただけで毎週の習慣を推定しない。

## 診断 SSE のイベント

SSEブロックは `event: <name>\ndata: <JSON>\n\n`。JSONはUTF-8で送られる。

| 順序 | event | data | 発生タイミング |
| --- | --- | --- | --- |
| 1 | `post` | `{"post": Post}` | 診断対象投稿をすべて取得した後、投稿一覧の順に全件送信。各投稿を送るたび手がかり抽出を待つわけではない。 |
| 2 | `clues` | `{"post_id":"…","clues":[Clue,…],"error":string|null}` | 抽出処理が完了した投稿ごと。抽出処理の完了順。成功時は `error:null`。投稿単位の抽出失敗時は空の `clues` とエラー文字列を送る。 |
| 3 | `conclusions` | `{"clues":[全Clue,…],"photo_place_results":[PhotoPlaceResult,…],"profile_claims":[ProfileCandidateSet;29],"profile_relations":[ProfileRelation,…],"profile_claim_suggestions":[post_id,…],"web_facts":[WebFact,…],"web_lookup_status":status,"external_profile_results":[ExternalProfileResult,…],"external_lookup_status":status,"owner_profile_text":string,"self_report_clues":[Clue,…]}` | 旧SSEイベント名を transport compatibility のため維持するが、`conclusions` 値は返さない。全投稿の抽出後に1回送信し、Bluesky/demoの公開結果は29件の `ProfileCandidateSet` を唯一のプロフィール結果とする。`photo_place_results` は画像単位の観測候補。ローカル候補がunknown/ambiguousのとき、専用同意済み・安全なClueがある場合だけBrave Place Search補完を行う。検索語は画像内のregionを持つ高確度OCR/VLM `shop` / `landmark` / `station_sign` の名称に限定し、診断全体で最大3クエリ。`country=JP`は検索範囲指定にすぎず、採用結果の `postal_address.country` が `JP` のときだけ候補に使う。タイトルは送信した名称と正規化後に完全一致するものだけ採用する。送信値は名称のみで、写真・crop・embedding・本文・人名・住所・郵便番号・DID・投稿URI・ハンドルは送らない。外部候補は未確認で、公式/公的な独立根拠がない限り所在地を断定しない。Braveの一時ID・画像thumbnail/snippetは保存しない。写真内に対象物が見える意味の `visible_in_frame` だけを生成し、写真撮影地点・本人の位置を直接主張しない。PhotoPlaceResult単独からprofile claimを作らない。`profile_claims`の`residential_area`は、local-onlyの許諾済みPOI候補と候補名に係る本人の明示的家周辺文脈、別投稿の独立した同地域根拠がそろった場合だけ別の弱い推論経路で作る。`WEB_SEARCHED`候補、引用/旅行/訪問/否定、単なる地域名言及、曖昧候補は根拠にしない。`profile_relations` はスコアを持たない関係（RulesX X1 の通学関係を含む）と、その関係全体を支える根拠経路。片側候補の全経路が消えた場合、または根拠投稿が削除された場合は表示から除く。`profile_claim_suggestions` は候補プール全体の根拠経路から選んだ最大3件。既存 `plan` イベントも続けて送る。
| 4 | `plan` | Simulation ＋ `"posts":[{"post_id","broken"},…]` | 推理の後に1回。`delete` は29項目の `ProfileCandidateSet` について、`PROFILE_ATTRIBUTE_WEIGHTS` に従い属性が丸ごと崩れる重み合計・失われる候補数・投稿数の少なさ・診断順で最大3件選ぶ（`plan_claims_json` / `plan_profile_candidate_deletion`）。`posts` は各投稿だけを消したときに崩れる `ProfileAttribute` で、組み合わせで初めて崩れる候補などでは空になりうる。候補がなければ `delete` は空。 |
| 5 | `done` | `{"posts_seen":number}` | 正常完了時に1回。 |

### 失敗・切断の現状

- 投稿単位の抽出失敗は `clues.error` に載る。現行パイプラインはその後も残りの処理を続け、集まった手がかりで `conclusions`、続けて `done` を送る。したがって `done` は全投稿の抽出成功を意味しない。
- `post`、抽出器の準備、Bluesky投稿取得など診断全体の失敗は、ストリーム開始前なら通常のHTTPエラー（例: 401/502/503）。ストリーム開始後に起きた例外を表す専用 `error` SSE イベントは現行実装・型にない。接続が途中終了すれば画面側は `done` 不達として「診断の途中で接続が切れました」とエラー表示する。
- クライアントは未知のイベント名を無視し、既知イベントの不正な形は不正応答として扱う。`done` 前の正常なEOFも切断エラー。
- 再実行開始時、画面は前回の投稿・手がかり・結論をクリアする。画面離脱時は AbortController で通信を中断する。
- SSEのイベント順序や部分失敗時の画面表現をさらに整える作業は Issue #46 の範囲。

### プロフィール推定と公開Web検索

- `profile_claims` は `home_room` を除く対象29属性（従来の24属性＋`age` / `birthday` / `occupation` / `active_time` / `routine`）を各1件ずつ返す。未推定属性も `unknown` または `conflict` として含め、候補のない属性を省略しない。形式は `{"attribute":ProfileAttribute,"status":"candidate"|"ambiguous"|"unknown"|"conflict","candidates":[ProfileCandidate,…],"candidate_pool":[ProfileCandidate,…],"reason":string|null,"conflicting_evidence":[ProfileEvidence,…]}`。`unknown` / `conflict` は `candidates` と `candidate_pool` が空で理由あり、`candidate` は表示候補1件、`ambiguous` は表示候補2〜3件。候補値は NFKC + trim + lowercase 後に重複させない。明示的な否定や矛盾の根拠は `conflicting_evidence` に入れ、候補値自体は作らない。
- `profile_relations` は、本人投稿中の明示関係と、別投稿で型付き手がかりにより独立して観測された既存候補だけを結ぶ無得点の表示情報。駅名が一致しただけで住居・勤務先・学校の候補を作らない。新しい `regular_station` 経路は別の本人投稿にある型付き自宅最寄り駅観測と、定期的な「自宅最寄りから通勤」文をAND根拠として持つ。両投稿の時刻は有効な時差付き日時で、間隔90日以内、移動・転居等の文脈がない場合のみ作る。値は「投稿時点の通勤利用駅候補」であり、現在の利用を保証しない。候補値から別候補値を導かず、同じ投稿・根拠の重複を独立証拠として数えない。
- 関係の形は `{"kind":ProfileRelationKind,"left":ProfileRelationEndpoint,"right":ProfileRelationEndpoint,"evidence_paths":[ProfileEvidencePath,…]}`。端点は候補なら `{"kind":"profile_candidate","attribute":ProfileAttribute,"value":string}`、明示された通勤・通学先なら `{"kind":"commute_destination","value":string}`。候補の削除後に端点のどちらか、または関係を支えるAND根拠経路が残らなければ、関係を表示しない。
- `ProfileCandidate` は `{"rank":number,"value":string,"confidence":number,"status":"found"|"weak","evidence":[ProfileEvidence,…],"evidence_paths":[ProfileEvidencePath,…],"assessment":ClaimAssessment,"observed_at":string|null,"counter_evidence":[ProfileEvidence,…]}`。confidence は校正済み確率ではなく順位付けのスコア。`candidate_pool` は根拠経路を持つ値を順位順に全て含み、rank は1始まりで連続する。表示前に根拠経路と観測品質の必須条件を満たす。最上位候補が `weak` なら、スコア差にかかわらず順位上位の `weak` 候補を最大3件表示する。最上位が `found` なら、スコアが最上位から0.15以内の同じ `found` 候補を最大3件表示する。その他は `candidate_pool` に残すが `candidates` には表示しない。`ambiguous` は2件以上の表示候補がある場合に使う。
- `ProfileEvidencePath` は `{"evidence":[ProfileEvidence,…],"confidence":number,"provenance":"direct_disclosure"|"combined_inference"|"unclassified"}`。これは候補値を支える完全な代替経路ごとの出所分類。`direct_disclosure` はその経路が候補値そのものを直接公開する場合、`combined_inference` は別々の情報を結びつけて候補値を導く場合、`unclassified` は分類できない既存・移行経路を表す。未指定の旧経路は安全側で `unclassified` とする。関係だけを本人が申告した手がかりは、対象値を別の観測と結びつける `combined_inference` 経路の根拠になりうる。削除後も `direct_disclosure` または `unclassified` 経路が残る `found` 候補は `found` を保つ。残る経路がすべて `combined_inference` の場合は `weak` に下げる。
- 候補は根拠経路がある値だけを含む。メイン結果は候補のある項目だけ表示し、29属性すべてのセットはAPIと内部型に保持する。値は候補カード1つだけ表示し、同じ値に直接公開と組合せ推定の両方の経路があれば、カード内に両方の出所ラベルを付ける。画面の直接公開ラベルは `自分で直接公開`、組合せ推定は `投稿の組み合わせから推定` とし、組合せ経路に公開Webの根拠がある場合は `投稿と公開Webから推定` とする。根拠経路が `unclassified` の場合は推定と表示しない。候補を正解と断定せず、値はログイン中の本人にそのまま表示する。
- `realtime_location` 候補には、根拠投稿の時刻を timezone-aware ISO 8601 の `observed_at` として必須で返す。診断時に投稿時刻が未来、欠落、または15分を超えて古い場合は候補にせず `unknown` にする。画面表示後に15分を超えた場合も、現在地を示す文言を外し、投稿時点の情報として表示する。
- 仮除外は `candidate_pool` 全体の根拠経路を除外投稿に合わせて再評価する。画面は再評価後の上位3件だけを表示し、全根拠候補数・表示候補数・候補順位の変化を示す。これは新しい投稿や根拠を使った推理の再実行ではない。
- `profile_claim_suggestions` は診断済み投稿の組合せを最大3件まで調べ、confidence 0.5以上の完全経路がすべて失われる候補値を再評価する。属性の重み合計（`PROFILE_ATTRIBUTE_WEIGHTS`）・失われる候補値数・投稿数の少なさ・診断順の順に選ぶ。値の順位変更だけでは属性が崩れたと数えない。Bluesky 診断の `plan` / `/api/simulate` / `/api/delete` および `/api/demo/*` と同じ29項目候補ベースを用いる。
- 公開Web検索は `public_web_lookup_consent` の診断単位同意がある場合だけ行い、本人の公開Blueskyハンドルと固定 `site:` 演算子のみ送る。写真場所検索は別の `photo_place_web_lookup_consent` が必要で、検索語は安全検査を通った画像内OCR/VLMの施設/地標/駅名に限る。外部検索は候補不足・競合のときだけで、最大3クエリ/診断・5結果/クエリ。写真場所検索は `MOCK_MODE=0`、Braveキーあり、`DIAGNOSE_DAILY_LIMIT > 0` の場合だけ有効であり、上限が0（無制限）なら同意済みでも外部通信を行わず検索利用不可として表示する。これは写真場所検索だけの費用ガードで、既存プロフィール検索の動作は変えない。BraveキーはAPIプロセスだけへ渡し、Composeではリポジトリ直下の `.env` をwebコンテナに渡さない。名前・文字列はログ・DB・キャッシュに保存せず、外部結果も診断のセッションメモリ内だけに置く。Brave APIの応答IDは約8時間で失効するため保存しない。`country=JP`で検索範囲を指定し、応答の郵便住所国もJPであることを確認する。検索結果名がqueryに完全一致しないものは採用しない。写真・crop・embedding・本文・プロフィール文・人名・住所・郵便番号・DID・投稿URI・ハンドルはPlace Searchへ送らない。両検索語はBraveで最大90日保持される。Braveの有料プランと支払情報が必要なため運営側が費用を負担する。`DIAGNOSE_DAILY_LIMIT=3`（本番例）の場合はアカウント1日最大3診断×3検索で最大9クエリ/日となる。費用上限を保つため本番でこの制限を0（無制限）にしない。モックとキー未設定時は外部通信を行わない。
- `external_profile_results` は検索候補と、本人プロフィール/投稿に記載されたURLと照合した候補を返す。これは公開URL上のリンク関係を示すだけで、実世界の本人確認や記事の執筆者確認を意味しない。検索結果本文の取得はしない。`MOCK_MODE=1` は固定fixtureのみで外部通信しない。

## 担当境界とデータ受け渡し

担当記号はIssueの記述にあるA/B/C/Dを使い、個人名やIssueにない合意内容は補わない。

| 担当 | 現在の責務・境界 | 主な受け渡し |
| --- | --- | --- |
| A | Web画面・操作・結果表示。APIとの通信、型検証、診断中の状態表示を担当。 | `web/src/types` の `Post`, `Clue`, `DiagnoseEvent`, `SessionResponse` と `web/src/lib/api.ts` を介してJSON/SSEを受け取る。Aの仮除外比較画面はIssue #69。 |
| B | 投稿単位の写真/本文から観測手がかりを抽出する担当範囲（Issue #60）。現行 `detect/` は抽出器・OCR/VLMクライアントを持つ。 | 入力は`Post`と画像bytes、出力は `PostExtraction(post_id, clues: Clue[])`。api pipelineが受け取りSSE `clues` と `conclusions.clues` へ渡す。独立 `POST /api/detect` の本番処理は未実装。 |
| C | 手がかりからの推理ルール、プロフィール推定・削除前後計算の担当範囲（Issue #59/#61/#65）。 | 入力は `Clue[]`、`Post[]`、必要な地名辞書。現行 `engine` の `infer` は試作 `Conclusion[]` を返し、`clue_indices` で入力Clueを参照。`planner` の `plan`・`simulate` は `infer` をかけ直して Simulation を返す（PR #77）。候補セット推定と候補プールの再評価は別の実装経路に接続済み。 |
| D | API、Bluesky本人セッション/投稿取得、診断パイプライン、各担当間の統合（Issue #38/#40/#45/#48）。 | Cookie付きHTTPを受け、`Post[]`→Bの抽出→`Clue[]`→Cの推理→SSEイベントとしてAへ渡す。`plan` イベントと `POST /api/simulate`（Issue #48 の最小版）で、Cの `tkb_engine.planner` を画面へ渡す。 |

**依存の流れ:** A ⇄ D(API/SSE) → B(抽出) → D(集約) → C(推理) → D(SSE) → A(表示)。型の共有元はPythonでは`common/`、TypeScriptでは`web/src/types/`。API固有のログイン要求/応答は `api/src/tkb_api/schemas.py` と `web/src/types/session.ts` で対応する。

## まだ実装されていない目標機能

- （旧目標・現行契約ではない）16項目プロフィールの `found/weak/unknown` 共通出力。現行は `home_room` を除く29項目の候補セットを返し、候補スコアと根拠を含む。
- （旧目標・現行契約ではない）16項目プロフィールでの削除候補・仮除外。現行は Bluesky 診断・`/api/demo/*` とも29項目候補セットと重みづけプランに一本化済み（Threads `/api/threads/simulate` は互換のため `Conclusion[]` を継続）。
- Blueskyログイン時以外の本番画像/本文抽出の統合完了確認。独立detectエンドポイントはモックのみで、本番は501。
- SSEの全体失敗イベント、途中切断後の再開・再送プロトコル。

これらはAGENTS.mdの目標やIssueの後続範囲であり、この文書の現行契約には含めない。

## X 専用の読み取り診断（`poc/x-local-text`）

Bluesky の `/api/session`・`/api/diagnose`・`/api/simulate` とは独立した `/api/x/*`。X の OAuth と診断は専用の HttpOnly `x_tkb_session` Cookie（Path `/api/x`）を使う。X の実投稿は用途承認・費用承認・上流クエリログ対策の設定がそろうまで拒否する。実X投稿の本文は loopback の Ollama のみに送る。`X_GPU_DEMO_ENABLED=1` で許可した場合に限り、固定の架空X投稿を既存VLMへ送る別セッションを作れる。結果はプロセスメモリだけに置き、X 投稿の実削除・結果共有は行わない。

| メソッド・パス | 入力 | 応答・動作 |
| --- | --- | --- |
| `GET /api/x/config` | なし | `mock_enabled, gpu_demo_enabled, live_enabled, max_posts`。秘密設定は返さない。 |
| `POST /api/x/mock/session` | `{"consent":true}` | `X_MOCK_MODE=1` のときだけ架空アカウントのセッションを発行。 |
| `POST /api/x/mock/gpu-session` | `{"consent":true}` | `X_MOCK_MODE=1` と `X_GPU_DEMO_ENABLED=1` のときだけ、固定の架空投稿をVLMで診断するセッションを発行。送信先は既存ガードを通す。X APIには接続しない。 |
| `POST /api/x/start` | `{"consent":true}` | 用途・費用承認が有効なときだけ PKCE S256 の `authorize_url` と開始 Cookie を返す。 |
| `GET /api/x/callback` | X の `state,code` と開始 Cookie | state/PKCE を照合し、トークン交換と本人確認の後 `/x` へ 303。 |
| `GET /api/x/session` | X セッション Cookie | `username, mock`。未認証401。 |
| `DELETE /api/x/session` | X セッション Cookie | セッション・結果をメモリから削除、204。 |
| `POST /api/x/diagnose` | X セッション Cookie | `DiagnosisSnapshot` と `elapsed_ms, mock`。実経路は本人の投稿を最大30リソース読み、Ollama本文抽出→既存推論。2回目はメモリの結果を返し再課金しない。 |
| `GET /api/x/diagnosis` | X セッション Cookie | 直近の完了結果。なければ404。 |
| `POST /api/x/simulate` | `{"delete":[診断済み投稿ID]}` | 既存 `Simulation`。X API・モデルは再呼出ししない。 |
| `POST /api/x/rediagnose` | 同上 | 除外後の `posts, clues, conclusions, plan, mock` を再計算。X API・モデルは再呼出ししない。 |

X の状態変更 API は同一オリジンの `Origin` ヘッダーを要求する。投稿IDは `x:<numeric id>`、画像は空配列。`clues` と `conclusions` の根拠番号は既存の形を再利用する。429は503と `Retry-After` を返す。詳細な設定・規約・費用は [x-poc.md](x-poc.md)。

## Threads 専用の読み取り診断

`/api/threads/diagnose` と `/api/threads/diagnosis` は、共通パイプラインの24属性候補セットを Threads 画面向けの従来の `ProfileItem[]` に変換して返す。表示対象の候補だけを平坦化し、候補のない属性は省略する。`/api/threads/rediagnose` は仮除外後の根拠経路を再評価し、返却する `clues` に合わせて根拠番号を振り直す。Threads の結果は専用セッションのメモリに置き、投稿の実削除は行わない。
