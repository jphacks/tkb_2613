# 「みーつけた」本番環境 脆弱性診断 途中報告（カテゴリ13）

[← 目次](README.md)

- 日付: 2026-11-10（本日限り・管理者許可済み）
- 対象: `<公開URL>`
- 範囲外: Bluesky 本体、cdn.bsky.app、他の AWS リソース、他人のアカウント
- 制約: 手動または 1 秒 1 件以下。WAF レート制限と 1 アカウント 1 日 3 回の診断上限は有効なまま。実削除は指定のデモ投稿 1 件のみ
- 進捗: GET のみで 27 リクエスト。認証・診断・GPU・SSM は未使用
- 位置づけ: **途中経過。未検証領域を含む**

## 結論

| 高 | 中 | 低 | 情報 |
|---|---|---|---|
| 0 | 1 | 3 | 2 |

重大な穴は未検出。ただし未検証領域が残っており、クリーンではない。想定外の挙動（500・他人のデータ・意図しない削除）は未発生。

## 要対応（優先順）

### F-1（中）CSP 未設定

- 実測: `Content-Security-Policy` が HTML・JSON 双方に無い。`X-Frame-Options`・`nosniff` はあり即悪用ではないが、OAuth コールバックを扱う面で多層防御が1枚欠ける。
- 再現: `curl -sS -o /dev/null -D - <公開URL>/`
- 修正案: CloudFront レスポンスヘッダポリシーに `default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`。inline が必要な箇所のみ nonce（現状 nonce 未使用）。

### F-2（低）HSTS に `includeSubDomains` が無い

- 実測: `strict-transport-security: max-age=31536000` のみ。max-age は充分長く実害は小さい。
- 修正案: `max-age=31536000; includeSubDomains`（移行予定が無ければ preload は見送り可）。

### F-3（情報・低）スタック識別子の露出

- 実測: `x-powered-by: Next.js`、`server: uvicorn`、`/api/features` が無認証で `auth_mode` を返す。
- 修正案: `poweredByHeader: false`。`auth_mode` はクライアント分岐に必要なので維持可。

### F-4（低）`/auth/callback` が異常時も 200

- 実測: `code`/`state` 無しでも 200 でログイン画面へ戻る。エラーコードが無く、state 検査の成否をステータスで判別できない。
- 修正案: state 欠落・不一致は 400 を返し `/?error=state_mismatch` 等で区別。本文は汎用のまま。

## 問題なしと確認できた点

| テスト | 期待 | 実測 | 判定 |
|---|---|---|---|
| 404 / 401 の `Cache-Control` | no-store 系 | `private, no-cache, no-store, max-age=0, must-revalidate` / `no-store, no-transform` | OK |
| エラー時の内部情報 | 出さない | スタック・内部パス・独自エラーページの混入なし | OK |
| `X-Content-Type-Options` | nosniff | あり（双方） | OK |
| `X-Frame-Options` | SAMEORIGIN 以上 | SAMEORIGIN（双方） | OK |
| `Referrer-Policy` | 厳しめ | `strict-origin-when-cross-origin` | OK |
| `Vary` | 適切 | 404: `rsc, next-router-*` / 401: `Origin` | OK |
| 未知パス | 内部情報なし | Next 既定 404 文言のみ | OK |
| API 未知パス | 内部情報なし | `{"detail":"Not Found"}` | OK |
| `/openapi.json` `/api/docs` | 非公開 | 全て 404 | OK |
| `/api/session`・`/api/diagnosis`（無認証） | 401 | 401・本文は汎用 | OK |
| `/share`（トークンなし） | 汎用文言 | 「リンクが無効か、有効期限が切れています」 | OK |

## 構造として判明したこと（設計判断に影響）

- `/` は Next.js、`/api/*` は **Next を経由せず uvicorn へ直接**到達（`server: uvicorn`）。内部経路の検査対象は `/auth/*`（Next 側）。
- セッションは Cookie 依存で、クライアントは全て `credentials: include`。ログインは `/auth/start` が `redirectUrl` を JSON で返しクライアント遷移。
- 共有リンクは `/share#<token>`（フラグメント＝サーバーに送られない）。トークンは `[A-Za-z0-9_-]{32,128}` で検証。
- `share_enabled` は現在 **false**。

## 未検証（この報告時点で白ではない）

| 項目 | 阻害要因 | 必要なもの |
|---|---|---|
| 外部から GPU（vLLM/OCR）・api 内部ポートへ届かないこと | AWS 読み取り未取得 | `aws` 認証、またはコンソール目視（SG インバウンド・公開 IP・メタデータ設定） |
| OAuth の state 使い回し／すり替え／Cookie 属性／ログアウト／パスワードログイン無効 | POST 未実施 | curl 2 本 |
| `/auth/*` がシークレット無しで外から叩けるか | 同上 | 同上 |
| 削除の拒否・確認ダイアログ | GPU ヘルスチェック待ち | ヘルスチェック成功の連絡＋診断 1 回 |
| 閲覧リンクの期限・ID 推測性・削除 UI 不在 | `share_enabled=false` | 有効化の可否判断 |
| IMDSv2 強制・実行ユーザー・ログ混入 | SSM 未実施 | 読み取りコマンドの実行 |

## 運用上の前提

- 診断スロットは 1 アカウント 3 回/日。使う直前に宣言する。
- GPU は検査のため稼働中（約 $2.24/時）。時間制約あり。
- SSM は読み取りのみ。ファイル変更・再起動・パッケージ導入・ポート開放・IAM/SG 変更は提案に留める。
- 秘密値（`.env`・トークン・`INTERNAL_AUTH_SECRET`）は「有無／長さ」のみ報告。
- 投稿本文・写真・ログ本文は外部に送らない。見るのはステータス・ヘッダ・エラー文言の形まで。
- 想定外（500・他人のデータ・意図しない削除）が出たら即停止して共有。

## 次のアクション

1. F-1 の修正可否を決める（今日は検出まで、修正は別途でも可）
2. curl 2 本（パスワードログイン無効確認・`/auth/start` の Set-Cookie と state 形状）
3. SG・公開 IP・IMDS の3点を目視で共有（AWS 認証を避ける場合）

---

本報告は途中経過。未検証項目の結論は確定していない。数値・ヘッダは 2026-11-10 12:02 UTC 時点の実測。
