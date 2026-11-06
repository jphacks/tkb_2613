# 認可・入力検証・取得先ガード テスト報告（カテゴリ2〜5）

- 対象: みーつけた api（FastAPI） / commit df27bac
- 実施日: 2026-11-06 / ローカル実施・破壊的操作なし（実削除なし）
- 環境: 未認証・ヘッダ・CORS・入力検証は本番モード(:8001)。ログインが要る確認（IDOR・削除の件数境界・`at://`検証）はモック(:8002, `SESSION_TTL_MINUTES=30`)。画像取得先ガードとモデル送信先ガードは関数の単体検証
- 認証境界（カテゴリ1）は [security-auth-boundary.md](security-auth-boundary.md) を参照

## 判定

脆弱性なし。検証項目すべて合格。設計上の注意2点（モデル送信先ガードの方式、公開時の `COOKIE_SECURE=1`）。

## 結果

| # | テスト | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| 認可 | 未診断セッションで simulate | 409 | 409 | 合格 |
| 認可 | 自セッションの診断を simulate（正当ID） | 200 | 200 | 合格 |
| IDOR | 他人DIDの投稿IDを混ぜて simulate | 422 | 422 | 合格 |
| 入力 | 空body / handle欠落 / password空 | 422 | 422 | 合格 |
| 入力 | 未知フィールド追加（`extra=forbid`） | 422 | 422 | 合格 |
| 入力 | JSONでない本文 | 422 | 422 | 合格 |
| 入力 | 422本文に送信値が反射されない | 反射なし | loc/msg/typeのみ | 合格 |
| 件数 | delete 0件（min1） | 422 | 422 | 合格 |
| 件数 | delete 11件（max10） | 422 | 422 | 合格 |
| 件数 | delete 512字超のID | 422 | 422 | 合格 |
| URI | `at://` に `..` 経路を混ぜて delete | 422 | 422 | 合格 |
| URI | like コレクション / 接頭辞偽装 / 空rkey | すべて拒否 | `is_own_post_uri`=False | 合格 |
| SSRF | 画像取得先: 非https / 別ホスト / メタデータIP / localhost / userinfo偽装 / サブドメイン偽装 | すべて拒否 | すべて拒否 | 合格 |
| CORS | 任意Origin(`evil.example`)への ACAO 反射 | 反射しない | ACAOなし | 合格 |
| CORS | 許可Origin(`localhost:3000`) | ACAO返却 | 返却 | 合格 |
| キャッシュ | 全応答の Cache-Control | no-store | `no-store, no-transform` | 合格 |
| detect | 認証不要・本番 / 型違い / 空body | 501 / 415 / 4xx | 501 / 415 / 415 | 合格 |
| ログ | モック診断のログに本文・画像・パスワード | 出力なし | 出力なし | 合格 |

## 所見

- 認可・IDOR: `simulate` / `delete` は「そのセッションで最後に診断した投稿」だけを対象にし、`known = {p.post_id for p in diagnosis.posts}` に無いIDは422で拒否。セッションは番号札（Cookie）単位で隔離され、他セッションの診断結果には触れられない。診断前は409。
- `at://` 検証: `is_own_post_uri` は「`at://<本人DID>/app.bsky.feed.post/` で始まり、rkey が空でなく `/` を含まない」ことを要求。他人DID・`..` 経路・別コレクション・接頭辞偽装（`...post.evil`）・空rkey はすべて False（拒否）。削除の二段構え（診断リスト照合＋URI検証）が効いている。
- 入力検証: 全リクエストモデルが `extra="forbid"`。未知フィールドは422。バリデーション応答は `_validation_error` が loc/msg/type だけに整形し、送信したパスワードや値は反射しない。
- 画像取得先（SSRF）: `fetch_images` は `scheme=="https"` かつ `hostname==cdn.bsky.app` だけを許可。メタデータIP(169.254.169.254)・localhost・userinfo偽装(`cdn.bsky.app@evil`)・サブドメイン偽装(`cdn.bsky.app.evil`)はすべて拒否。`follow_redirects=False` によりリダイレクト追従もなし。
- CORS: `allow_credentials=True` だが、Starlette の CORS は許可Originにだけ `Access-Control-Allow-Origin` を返す。`evil.example` には ACAO を返さないため、ブラウザは資格情報付きクロスオリジン読み取りを許可しない。任意Origin反射なし。
- キャッシュ: 全応答に `Cache-Control: no-store, no-transform`。認証応答が中継（CDN）に保存される懸念なし。

## 設計上の注意（脆弱性ではない）

- **モデル送信先ガードは拒否リスト方式**（[detect/src/tkb_detect/guard.py](../detect/src/tkb_detect/guard.py)）。
  `ensure_team_endpoint` は openai・x.ai など既知の第三者AIホストを拒否するが、リストに無いホスト（例: `evil.example`、`169.254.169.254`）は通過する。送信先 `VLM_BASE_URL` はユーザー入力ではなくチームが設定する値のため、実害は「設定ミス時の保険が弱い」程度。より堅くするなら、チームのホストだけを通す許可リスト方式が本筋。
- **`cookie_secure` 既定オフ**（[api/src/tkb_api/config.py](../api/src/tkb_api/config.py)）。
  ローカルHTTPでは正常。本番のHTTPS公開時に `COOKIE_SECURE=1` を入れ忘れると、セッションCookieが平文で送信され得る。デプロイ時のチェック項目とする。
- **`/api/detect` は認証不要**。本番では501を返すだけで現状無害だが、本実装時は認証・レート制限の要否を再検討する。

## 未実施（別途）

- 実VLM（RunPod）へのプロンプトインジェクション確認（投稿本文の指示でモデルの推定・削除提案を操作できるか）。実モデルにデモ本文を送るため、実施是非を要相談。
- 実削除の最終確認は、消えてよいデモ投稿で手動1件を推奨。
