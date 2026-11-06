# セッション管理・Cookie属性（カテゴリ2）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 実施日: 2026-11-06 / ローカル実施・破壊的操作なし
- 環境: ログインが要るため モック(:8002, `MOCK_MODE=1`, `SESSION_TTL_MINUTES=30`)。モックログインは架空DIDを返し Bluesky に接続しない

## 判定

脆弱性なし。検証項目すべて合格。運用上の注意1点（公開時の `COOKIE_SECURE=1`）。

## 結果

| # | テスト | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| 一連 | login→確認(GET /session)→logout(DELETE /session) | 正常遷移 | Cookie発行→200→204 | 合格 |
| 属性 | `HttpOnly` | あり | あり | 合格 |
| 属性 | `SameSite` | Lax | `SameSite=lax` | 合格 |
| 属性 | `Secure` | ローカルは無し | 無し（`cookie_secure`既定false） | 合格※ |
| 属性 | `Max-Age` / `Path` | TTL / `/` | `Max-Age=1800` / `Path=/` | 合格 |
| 固定 | ログイン前に仕込んだCookie(`tkb_session=ATTACKERCHOSEN123`)を引き継ぐか | 引き継がない | 新IDを発行（攻撃者指定IDは破棄） | 合格 |
| 失効 | ログアウト後に同じCookieで GET /session | 401 | 401 | 合格 |
| 同時実行 | `SessionStore` を20スレッド×200回 create/get/delete | 例外なし | 例外なし（`threading.Lock`） | 合格 |

※ `Secure` は運用上の注意。下記参照。

## 所見

- ログイン時に `store.create` が新しいセッションID（`secrets.token_urlsafe(32)`）を発行し、`set_cookie` で上書きする。クライアントが事前に設定したCookie値はサーバに記録されないため、**セッション固定は成立しない**。
- `DELETE /api/session` でサーバのメモリ（`SessionStore`）からセッションが削除され、以後は同じCookieでも401。Bluesky のトークンもメモリ上だけで、ログアウトで破棄される。
- Cookie属性は `HttpOnly`（JSから読めない）＋ `SameSite=lax`（クロスサイトのPOSTでは送られない＝CSRF緩和）。
- 同時実行/TOCTOU: `SessionStore` は `threading.Lock` で create/get/delete/診断保存を保護。20スレッド×200回の並行アクセスで例外は発生しなかった。

## 運用上の注意（脆弱性ではない）

- `cookie_secure` 既定オフ（[api/src/tkb_api/config.py](../../api/src/tkb_api/config.py)）。ローカルHTTPでは正常だが、本番HTTPS公開時は `.env` で `COOKIE_SECURE=1` を設定する。未設定だとセッションCookieがHTTPでも送られ得る。
- 期限切れ（TTL境界での失効・メモリ破棄）の実挙動は [01-auth-boundary.md](01-auth-boundary.md) カテゴリ④で確認済み。
