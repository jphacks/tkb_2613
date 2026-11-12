# X連携と公開情報チェックの実装・運用条件（2026-11-12）

## 実装範囲

`/x` と `/api/x/*` は Bluesky・Threads のセッションや診断エンジンから独立している。X OAuth 2.0 Authorization Code Flow with PKCE（S256）で本人を認証し、`/2/users/me` の ID と一致する `/2/users/:id/tweets` の投稿だけを最大30件取得する。画像、外部検索、人物照合、推定、投稿の変更・削除は扱わない。

X専用の公開情報チェックは、投稿本文にそのまま現れる `place`（都道府県・市区町村）、`station`、`weekday`、`time`、`school` だけを保守的な正規表現で抽出する。値ごとに根拠投稿と記載件数を返し、仮除外後はメモリ内の投稿から再集計する。Bluesky・Threadsの `Clue`、`Conclusion`、推論ルール、モデルは呼ばない。

X専用セッション、OAuth state、PKCE verifier、アクセストークン、投稿、結果はAPIプロセスのメモリだけに置く。CookieにはランダムなセッションIDまたは認可開始nonceだけを入れ、`HttpOnly`、`SameSite=Lax`、X API専用Pathを設定する。セッションは既定30分で失効し、ログアウト時には投稿・結果・トークンを即座に破棄する。コールバックの `code` と `state` はuvicornアクセスログから伏せる。上流プロキシでもクエリ文字列を記録しない設定が必要。

`X_MOCK_MODE=1`（既定）は固定の架空投稿だけを使い、X APIやモデルへ接続しない。実OAuthと実投稿取得は次の全条件を満たすときだけ開始できる。

- `X_MOCK_MODE=0`
- `X_USE_CASE_APPROVED=1`（Xに具体的な用途を説明し、利用可能と確認済み）
- `X_PAID_READS_APPROVED=1`（チームの費用承認済み）
- `X_QUERY_LOGS_REDACTED=1`（全経路でcallback queryを伏せる設定を検証済み）
- `X_CLIENT_ID`と`X_CLIENT_SECRET`が設定済み

フラグは承認の代わりではない。現在はすべて有効化しない。

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

同じ診断結果はセッションメモリから返し、投稿取得を繰り返さない。テストはHTTPモックだけを使い、実Xリクエストや課金を発生させない。

## 利用規約上の判断

Developer Policyは、何を収集しどう使うかを利用者に明確に説明して同意を得ることを求め、ログインだけを同意とは扱わない。画面には対象カテゴリ、保持時間、仮除外、非実施事項を表示して明示同意を求める。

Restricted Usesはindividual profiling、センシティブ属性の推定、surveillance、facial recognitionなどを禁止する。Developer Policyのgeo-data条項は、X Contentに含まれる位置・地理情報をPostから切り離して保存・集計・キャッシュすることも禁止している。駅名・地名を値ごとに集計する今回の画面がこの禁止に該当しないとは判断できない。根拠Postへのリンクを維持し、住所等を導出しない設計でも未解決なので、Xからこの具体的な表示・一時メモリ保持を許可する書面回答を得るまで実投稿取得・分析を有効化しない。`X_USE_CASE_APPROVED=1` はこのgeo-data論点を含む回答を得た場合だけ設定する。

X Contentの削除・変更・保護化への同期、Postの表示要件、第三者提供条件も未解決。現実装は30分以内のメモリ保持・ログアウト削除・共有なしで影響を抑えているが、本番運用条件としてXへ確認する。

## EXPOで利用できる範囲

用途確認が未完了の間は `X_MOCK_MODE=1` の合成デモだけを提供する。来場者は地名・駅名・曜日・時刻・学校名の根拠と件数、元投稿、仮除外前後を操作できるが、自分のXアカウントでログインしたり実投稿を取得したりはできない。

実試験へ進む前提は、Xの用途確認、チームの課金承認、ConsoleのWeb App設定、creditとspending limit、HTTPS callback、Secretの安全な注入、全段のqueryログ伏せ、本人同意文面、削除・変更への運用方針を揃えること。最初の実試験はチーム所有のテストアカウント1件、`X_MAX_POSTS=5`、監視下で行い、その後フラグを戻してメモリ・ログ・請求を確認する。
