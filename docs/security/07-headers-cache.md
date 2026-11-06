# キャッシュ・レスポンスヘッダ（カテゴリ7）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 実施日: 2026-11-06 / ローカル実施・破壊的操作なし
- 環境: 本番モード(:8001)。SSE固有ヘッダはコード確認＋実測

## 判定

脆弱性なし。全応答に `no-store`。認証応答が中継（CDN）に保存される懸念なし。

## 結果

| # | テスト | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| 全応答 | `/health` の Cache-Control | no-store | `no-store, no-transform` | 合格 |
| 全応答 | 401（`/api/session`）の Cache-Control | no-store | `no-store, no-transform` | 合格 |
| SSE | SSE固有ヘッダ・keep-alive | → [12-sse.md](12-sse.md) | `X-Accel-Buffering: no` ほか実測 | 合格 |

## 所見

- `NoStoreMiddleware`（[api/src/tkb_api/main.py](../../api/src/tkb_api/main.py)）が全HTTP応答に `Cache-Control: no-store, no-transform` を付ける。`no-transform` は中継（Next.jsの中継）がgzip圧縮してSSEをためこむのを防ぐため。実測で `/health`・401応答の双方に付与を確認。
- SSE（`/api/diagnose`）は `media_type="text/event-stream"`、ヘッダ `Cache-Control: no-cache`・`X-Accel-Buffering: no`。イベント間が `sse_keepalive_seconds`（既定15秒）を超えると `: keep-alive` コメントを送り、中継の切断を防ぐ。
- 認証状態を含む応答がCDN等に保存され、別の利用者へ返る懸念はない。
