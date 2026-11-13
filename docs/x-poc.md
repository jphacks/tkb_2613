# X連携と公開情報チェックの実装・運用条件（2026-11-12）

## 実装範囲

`/x` と `/api/x/*` は Bluesky・Threads のセッションや診断エンジンから独立している。X OAuth 2.0 Authorization Code Flow with PKCE（S256）で本人を認証し、`/2/users/me` の ID と一致する `/2/users/:id/tweets` の投稿だけを最大30件取得する。画像、外部検索、人物照合、推定、投稿の変更・削除は扱わない。

X専用の公開情報チェックは、投稿本文にそのまま現れる `place`（都道府県・市区町村）、`station`、`weekday`、`time`、`school` だけを保守的な正規表現で抽出する。値ごとに根拠投稿と記載件数を返し、仮除外後はメモリ内の投稿から再集計する。Bluesky・Threadsの `Clue`、`Conclusion`、推論ルール、モデルは呼ばない。

X専用セッション、OAuth state、PKCE verifier、アクセストークン、投稿、結果はAPIプロセスのメモリだけに置く。CookieにはランダムなセッションIDまたは認可開始nonceだけを入れ、`HttpOnly`、`SameSite=Lax`、X API専用Pathを設定する。セッションは既定30分で失効し、ログアウト時には投稿・結果・トークンを即座に破棄する。コールバックの `code` と `state` は次のとおりログから伏せる。

| 経路 | 対応 | 確認 |
| --- | --- | --- |
| uvicorn のアクセスログ | `XCallbackAccessFilter` が `/api/x` 配下のクエリを丸ごと落とす（末尾スラッシュ・`//`・%エンコードの変形も） | `api/tests/test_x_log_redaction.py`：実 uvicorn に偽のコールバックを送り、403・400・502・500 のどれでもサーバー側のログと標準出力に残らない |
| FastAPI のエラーログ | 例外の文言・トレースバックにクエリは入らない | 同上（予期しない例外の 500 を含む） |
| Next.js の中継 | `/api/x/callback` だけ rewrites を使わず `app/api/x/callback/route.ts` で中継する。rewrites は api に届かないとき `Failed to proxy <URL>` とクエリごと出すため | `route.test.ts` と `scripts/check-x-callback-log-redaction.mjs`（本番ビルドで api 正常・500・停止の3通り。CI で実行） |
| Next.js 開発サーバーの受信ログ | `logging.incomingRequests.ignore` で除く（本番は受信ログを出さない） | — |
| CloudFront | 2026-11-12 時点でアクセスログ・リアルタイムログとも未設定。有効にすると `cs-uri-query` にクエリが入るので、有効にする場合はクエリの項目を外す | Terraform の状態で確認 |

`X_QUERY_LOGS_REDACTED=1` は、本番の経路（CloudFront の設定を含む）を承認日に見直してから設定する。

`X_MOCK_MODE=1`（既定）は固定の架空投稿だけを使い、X APIやモデルへ接続しない。実OAuthと実投稿取得は次の全条件を満たすときだけ開始できる。

- `X_MOCK_MODE=0`
- `X_USE_CASE_APPROVED=1`（Xに具体的な用途を説明し、利用可能と確認済み）
- `X_PAID_READS_APPROVED=1`（チームの費用承認済み）
- `X_QUERY_LOGS_REDACTED=1`（全経路でcallback queryを伏せる設定を検証済み）
- `X_CLIENT_ID`と`X_CLIENT_SECRET`が設定済み

フラグは承認の代わりではない。現在はすべて有効化しない。

どれか1つでも欠ければ（Client ID・Secret が空白だけの場合も）、`/api/x/config` の `live_enabled` は false になり画面に「Xでログイン」を出さない。`/start`・`/callback`・実トークンのセッションでの `/diagnose` も403で拒否し、X へは通信しない。`api/tests/test_x_approval_guard.py` と `web/src/app/x/page.test.tsx` で固定している。

## OAuth実装とWeb Appへの変更

X公式仕様では、Native AppとSingle Page Appはpublic client、Web AppとAutomated App or Botはconfidential clientである。このアプリはブラウザへ秘密を渡さず、FastAPIサーバーがcallbackとtoken exchangeを処理するため、Developer Consoleは **Web App** が適切。

Native AppからWeb Appへ変更しても、Authorization Code + PKCE、S256 challenge、state、scope、callbackの基本フローは同じ。差分はWeb AppがClient Secretを持ち、token endpointでサーバーからclient authenticationを行う点。現行 `_exchange` はSecretがあるとHTTP Basic認証、ないpublic clientではbodyに`client_id`を入れるため、設定変更後も互換性がある。Web App運用ではSecretを必須としてサーバー環境変数にだけ置く。

要求scopeは `tweet.read users.read` のみ。`offline.access` は要求せずrefresh tokenを保存しないため、access tokenは公式仕様上通常2時間で失効するが、アプリ側セッションはそれより短い30分で破棄する。callback URLは完全一致が必要。

## Developer Consoleで設定する項目

既存のEXPO用CloudFront origin `https://d2qyby5y8mc03f.cloudfront.net` を使う場合の値。配信先を変えた場合は、すべて同じ新originへそろえる。

| 項目 | 値 |
| --- | --- |
| App permissions | Read |
| Type of App | Web App, Automated App or Bot（画面上のWeb App選択肢） |
| Callback URI / Redirect URL | `https://d2qyby5y8mc03f.cloudfront.net/api/x/callback`（完全一致、query・fragment・末尾slashなし） |
| Website URL | `https://d2qyby5y8mc03f.cloudfront.net` |
| OAuth 2.0 scopes | アプリが要求する `tweet.read users.read` と一致。`offline.access` とwrite系は不要 |
| Client ID | Developer Console発行値をAPIサーバーの`X_CLIENT_ID`へ |
| Client Secret | 再生成・表示された値をAPIサーバーの`X_CLIENT_SECRET`へ。Git、チャット、ブラウザ、`NEXT_PUBLIC_*`には置かない |
| Terms of Service URL | `https://d2qyby5y8mc03f.cloudfront.net/terms` |
| Privacy Policy URL | `https://d2qyby5y8mc03f.cloudfront.net/privacy` |

アプリ側は `X_PUBLIC_ORIGIN=https://d2qyby5y8mc03f.cloudfront.net`、`X_CALLBACK_URL=https://d2qyby5y8mc03f.cloudfront.net/api/x/callback`、`COOKIE_SECURE=1` とする。Developer Consoleの変更はリポジトリからは行わない。

## API取得・課金

- `POST /2/oauth2/token`: 認可コードの交換。PKCE verifierとWeb Appのclient authenticationを使う。
- `GET /2/users/me`: 本人ID・usernameの確認。User Read 1 resource。
- `GET /2/users/:id/tweets`: 本人投稿の取得。返されたPost resource数に応じる課金。`author_id`をセッション本人IDと再照合し、リポストを除外する。

2026-11-12時点の公式料金表は通常のUser Readが `$0.010/resource`、Posts Readが `$0.005/resource`。本人確認1件と最大30投稿なら最大概算 `$0.16`（税等を除く）。Owned Readsの割引は「認証ユーザーがdeveloper appのownerでもある」場合なので、一般のEXPO来場者には前提としない。単価は変更されるため、試験直前にConsoleで最新価格、credit残高、spending limitを確認し、auto-rechargeは意図せず有効にしない。

同じ診断結果はセッションメモリから返し、投稿取得を繰り返さない。

### 偽の X API での E2E

`pnpm -C web test:e2e:x-fake`（CI の「X 偽API E2E」ジョブ）は、`web/e2e/fake-x/server.mjs` の偽の X（127.0.0.1:4010）、承認フラグをすべて1にした api（127.0.0.1:8011）、画面（localhost:3100）を立て、OAuth → 投稿の取得（`X_MAX_POSTS=5`）→ 集計 → 仮除外・再集計 → ログアウトでの破棄を Playwright で通す。X の認可画面は Playwright が偽の X へ差し替え、それ以外の x.com への通信は止めて0件であることを確かめる。偽の X は PKCE（S256）・Basic 認証・redirect_uri・30秒の認可コード・Bearer トークンを検証し、応答の形は公式ドキュメントの例（`/2/users/me`、ページ送りの `meta`）に合わせる。

api の向き先は `X_FAKE_API_BASE_URL` で変えるが、http の loopback で `COOKIE_SECURE=0`、`X_PUBLIC_ORIGIN` も loopback のときだけ起動でき、それ以外（本番の設定例を含む）では起動時に失敗する（`api/tests/test_x_fake_api_guard.py`）。偽の X は本番イメージに入れない（`web/.dockerignore`）。

### 1日の取得件数の上限（`X_DAILY_RESOURCE_LIMIT`）

既定は40。X を呼ぶ前に、読む可能性のある最大リソース数を予約する（OAuth 後の `/2/users/me` は1、投稿一覧は `max(5, X_MAX_POSTS)`）。上限を超えるなら X を呼ばずに429（`Retry-After` は次の UTC 0時まで）で断る。`/start` の時点で「本人確認＋1回の投稿取得」の分が残っていなければ認可画面へ進ませない。実際に返った件数が少なくても返金せず、保守的に数える。0 にすると実取得をすべて断る。

カウンタはAPIプロセスのメモリだけにあり、再起動で0に戻る。アプリ側の上限は誤操作の歯止めであって、最終の歯止めは Developer Console の spending limit にする。既定の40で1日に通るのは本人確認＋30件の取得1回分で、概算は最大 `$0.16`。テストはHTTPモックだけを使い、実Xリクエストや課金を発生させない。

## 利用規約上の判断

Developer Policyは、何を収集しどう使うかを利用者に明確に説明して同意を得ることを求め、ログインだけを同意とは扱わない。画面には対象カテゴリ、保持時間、仮除外、非実施事項を表示して明示同意を求める。

Restricted Usesはindividual profiling、センシティブ属性の推定、surveillance、facial recognitionなどを禁止する。Developer Policyのgeo-data条項は、X Contentに含まれる位置・地理情報をPostから切り離して保存・集計・キャッシュすることも禁止している。駅名・地名を値ごとに集計する今回の画面がこの禁止に該当しないとは判断できない。根拠Postへのリンクを維持し、住所等を導出しない設計でも未解決なので、Xからこの具体的な表示・一時メモリ保持を許可する書面回答を得るまで実投稿取得・分析を有効化しない。`X_USE_CASE_APPROVED=1` はこのgeo-data論点を含む回答を得た場合だけ設定する。

X Contentの削除・変更・保護化への同期、第三者提供条件も未解決（Postの表示要件は下の「投稿の表示要件」で対応）。現実装は30分以内のメモリ保持・ログアウト削除・共有なしで影響を抑えているが、本番運用条件としてXへ確認する。

## 投稿の表示要件

2026-11-12 に [Display requirements: Posts](https://docs.x.com/developer-terms/display-requirements) を読み、`web/src/components/x/XPostCard.tsx` で合わせた。api は `/2/users/me` に `user.fields=profile_image_url`、投稿一覧に `post.fields=…,entities,edit_history_tweet_ids` を足し（どちらも読むリソース数は変わらない）、診断結果の `x_display` に投稿者と投稿ごとの表示情報を入れる（`api/src/tkb_api/x_display.py`）。

| 要件 | 対応 |
| --- | --- |
| 投稿者のアイコン・表示名・@ユーザー名を常に出し、X のプロフィールへリンクする。アイコンは名前の左 | 対応。アイコンは `pbs.twimg.com`・`abs.twimg.com` の https だけを表示し、取れなければ頭文字で代える |
| 本文は投稿者の下の独立した行に出し、改変しない | 対応。本文の文字は区切って並べるだけで変えない（`segmentXText` のテストで、断片をつなぐと元の本文になることを確かめる） |
| @メンションはプロフィール、ハッシュタグは X の検索、URL は `display_url` を出して t.co へリンクする | 対応。範囲は X の仕様どおりコードポイント単位。範囲が壊れている・重なる・リンク先が x.com／t.co でないものは、ただの文字として出す |
| 日時を出し、permalink へリンクする | 対応（`https://x.com/<username>/status/<id>`） |
| 返信・リポスト・いいねの操作を出す。日時の横の「View on X」で代えてよい | 「Xで見る」で代える。ほかの SNS やサードパーティの操作は付けない |
| X のロゴを各投稿の右上に見える大きさで出す | 対応（各カードの右上に 20px） |
| 編集された投稿は、編集を日時のところで示し、最新の投稿へリンクする | 「編集済み」を日時の横に出す。日時のリンク先は最新の ID の permalink |
| タッチ端末では本文のまわりの余白も permalink へのリンクにする | 未対応（日時と「Xで見る」から開ける） |
| リポスト | 取得時に `exclude=retweets` で除くので出ない |
| 返信 | 別の要件（Display requirements: Replies）があり未確認。承認後の試験までに読む |
| 存在しない投稿のモックアップを使わない | 合成デモの架空投稿には X のロゴ・x.com へのリンクを付けず、「架空」「架空の投稿（Xの投稿ではありません）」と出す |
| 投稿を製品の宣伝や推薦に使わない | 使わない |

## 集計しない表示（`X_INFO_VIEW=highlight`）

既定は `aggregate`（今の表示：地名・駅名・曜日・時刻・学校名を値ごとに数え、根拠を並べる）。`highlight` にすると、api は値ごとの集計を作らず、投稿ごとに地名・駅名の位置（コードポイント単位の `start`・`end`）だけを返す。画面は本文の文字を変えずにその部分へ背景色を付けるだけで、値の一覧・件数・仮除外前後の件数の比較は出さない（`/api/x/simulate` は409）。仮除外は残りの投稿を出し直すだけになる。曜日・時刻・学校名には色を付けない。表示はセッションで診断したときの設定に固定し、途中で設定を変えても混ざらない。

Developer Policy の geo-data 条項（位置情報を Post から切り離して保存・集計しない）の論点を避けるための表示で、X への確認では `highlight` を基本の案として示す。ただし、ハイライトが表示要件の「本文を改変しない」に当たらないか（文字は変えず背景色だけ）は、あわせて X に確認する。

## EXPOで利用できる範囲

用途確認が未完了の間は `X_MOCK_MODE=1` の合成デモだけを提供する。来場者は地名・駅名・曜日・時刻・学校名の根拠と件数、元投稿、仮除外前後を操作できるが、自分のXアカウントでログインしたり実投稿を取得したりはできない。合成デモでも `/api/x` の POST は Origin を `X_PUBLIC_ORIGIN` と照らすので、本番の `.env` には `X_PUBLIC_ORIGIN=https://<公開オリジン>` と `X_CALLBACK_URL` が要る（`infra/aws.env.example`）。未設定（既定の `http://localhost:3000`）のまま `COOKIE_SECURE=1` で起動すると、api は起動時に警告をログに出す（起動は止めない）。Threads を開けているとき（`THREADS_MOCK_MODE=1` か `THREADS_ENABLED=1`）の `THREADS_PUBLIC_ORIGIN` も同じ。

実試験へ進む前提は、Xの用途確認、チームの課金承認、ConsoleのWeb App設定、creditとspending limit、HTTPS callback、Secretの安全な注入、全段のqueryログ伏せ、本人同意文面、削除・変更への運用方針を揃えること。最初の実試験はチーム所有のテストアカウント1件、`X_MAX_POSTS=5`、監視下で行い、その後フラグを戻してメモリ・ログ・請求を確認する。

## 承認が届いた日にやること

前提：X からの書面の回答で、用途（本人の投稿の自己点検）、geo-data 条項（地名・駅名の扱い。集計表示か `X_INFO_VIEW=highlight` か）、ハイライトが本文の改変に当たらないこと、の3点が確認できていること。チームで費用（最大概算と上限）を承認していること。どれかが欠けていれば、この先へ進まず `X_MOCK_MODE=1` のままにする。

### 1. Developer Console（人が画面で行う。リポジトリからは変えない）

1. 上の「Developer Consoleで設定する項目」の表どおりに、App permissions を Read、Type of App を Web App、Callback URI を `https://<公開オリジン>/api/x/callback`（完全一致）、Website・利用規約・プライバシーポリシーの URL を設定する。
2. OAuth 2.0 の scope が `tweet.read users.read` だけであることを確かめる。
3. Client Secret を再生成し、表示された値をその場で次の「秘密の置き場所」へ入れる。画面のコピーやメモを残さない。
4. Billing で最新の単価、credit 残高を確認し、**spending limit を小さく設定**する（例：数ドル）。auto-recharge は切ったままにする。

### 2. 秘密の置き場所

- `X_CLIENT_SECRET` は API サーバーだけに置く。Git、チャット、ブラウザ、`NEXT_PUBLIC_*`、`/opt/tkb_2613/.env` には書かない。
- 置き場所は、VLM の鍵と同じく AWS Secrets Manager（例：`tkb_2613/x-client-secret`）。`infra/tkb-app-start.sh` が起動時に読み、tmpfs の `/run/tkb_2613/api-secrets.env` にだけ書いて compose に渡し、終了時に消す形にする。そのために、Terraform で secret と EC2 ロールの `secretsmanager:GetSecretValue` を足し、起動スクリプトに `X_CLIENT_SECRET=` の行を足す変更を PR にする（承認日の作業。今はまだ入れていない）。
- `X_CLIENT_ID` は秘密ではないが、Secret と同じ経路か `.env` に置く。
- 値を入れた後、`docker compose exec api env` などで中身を画面に出さない。確かめるのは `GET /api/x/config` の `live_enabled` だけにする。

### 3. 設定を入れる順番（アプリの EC2 の `.env`）

1. `X_PUBLIC_ORIGIN=https://<公開オリジン>`、`X_CALLBACK_URL=https://<公開オリジン>/api/x/callback`、`COOKIE_SECURE=1` を確かめる。`X_FAKE_API_BASE_URL` は書かない（書くと起動に失敗する）。
2. `X_MAX_POSTS=5`、`X_DAILY_RESOURCE_LIMIT=12`（本人確認1＋投稿5の2回分）にする。
3. X の回答に合わせて `X_INFO_VIEW` を決める（geo-data の回答が集計を認めない場合は `highlight`）。
4. CloudFront のアクセスログ・リアルタイムログが無効のままか（有効なら `cs-uri-query` を外したか）を確かめてから `X_QUERY_LOGS_REDACTED=1`。
5. `X_USE_CASE_APPROVED=1`、`X_PAID_READS_APPROVED=1`、`X_MOCK_MODE=0` にして再起動する。
6. `GET /api/x/config` が `live_enabled: true`、`max_posts: 5` を返すことを確かめる。

### 4. チームのテストアカウントで試す

- 使うのはチームが持つテスト用の X アカウント1つだけ。投稿は架空の内容で、自宅周辺や他人の顔が分かるものを含めない。最初は投稿を5件程度にしておく。
- 2人以上で、画面とサーバーのログを見ながら1回だけ行う：同意 → Xでログイン → 認可 → `/x` に戻る → 公開情報を確認する → 仮除外 → ログアウトしてデータを破棄。

### 5. 確認項目

- [ ] 認可画面に出る scope が読み取りだけ（`tweet.read users.read`）
- [ ] コールバック後の URL にクエリが残らず `/x` に戻る
- [ ] api・web・CloudFront のログに `code`・`state`・トークン・投稿本文が出ていない（`/api/x/callback` の行がクエリなしで出ている）
- [ ] 取得した投稿が5件以下で、すべて本人の投稿（リポストを含まない）
- [ ] 投稿の表示が表示要件どおり（アイコン・表示名・@ユーザー名のリンク、X ロゴ、日時の permalink、「Xで見る」、メンション・ハッシュタグ・URL のリンク、編集済み）
- [ ] 仮除外・再集計（または再表示）で X を再び呼んでいない（Console の使用量が増えない）
- [ ] ログアウト後、`/api/x/session` と `/api/x/diagnosis` が 401
- [ ] 2回目のログインが `X_DAILY_RESOURCE_LIMIT` で429になる（上限が効いている）
- [ ] Console の使用量・請求が、本人確認1＋投稿5程度のリソース数と一致する

### 6. 終わったら戻す

- `X_MOCK_MODE=1`、`X_USE_CASE_APPROVED=0`、`X_PAID_READS_APPROVED=0` に戻して再起動し、`live_enabled: false` を確かめる。API プロセスの再起動でメモリ上のトークン・投稿・結果も消える。
- 結果（件数・所要時間・請求額・気づいたこと）を記録し、件数を増やすか、公開するかはチームで決め直す。
