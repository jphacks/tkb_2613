# SSE 契約・耐性（カテゴリ12）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 実施日: 2026-11-06 / ローカル実施・破壊的操作なし
- 環境: モック(:8002, `MOCK_MODE=1`)。keep-alive 誘発のため `MOCK_EVENT_INTERVAL_SECONDS=2`・`SSE_KEEPALIVE_SECONDS=0.3`
- 対応: [api-sse-contract.md](../api-sse-contract.md) の SSE 契約

## 判定

脆弱性なし。SSEヘッダ・keep-alive・途中切断の挙動はいずれも想定どおり。内部タスク解放は未検証。

## 結果

| # | テスト | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| ヘッダ | Content-Type | event-stream | `text/event-stream; charset=utf-8` | 合格 |
| ヘッダ | `X-Accel-Buffering` | `no` | `no` | 合格 |
| ヘッダ | Cache-Control | no-store | `no-store, no-transform` | 合格 |
| keep-alive | イベント間隔>設定値でコメント送信 | 送る | `: keep-alive` を6秒で2回観測 | 合格 |
| 途中切断 | 1秒で切断後にサーバが健全か | 健全 | `/health` 200・ログにエラーなし | 合格 |
| 敵対データ | 本文に改行・`event:`・`data:`・`\r\n` を含む投稿を `_sse` で出力 | 境界を壊さない | `event:`/`data:` 行は各1本、本文はJSONで完全復元 | 合格 |

## 所見

- `/api/diagnose` は `StreamingResponse(media_type="text/event-stream")`。ルートで `Cache-Control: no-cache`・`X-Accel-Buffering: no` を付け、`NoStoreMiddleware` がさらに `no-store, no-transform` に上書きする（中継がSSEをためこまないため）。
- `_with_keep_alive` が、イベント間隔が `sse_keepalive_seconds`（既定15秒）を超えると `: keep-alive` コメントを送る。間隔を詰めた設定で実際に送信を観測。
- クライアントが途中で切断してもサーバは健全を維持し、ログにエラー・例外は出なかった。

## 所見（敵対データ）

- `_sse` は `f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"`。本文の改行・CR・`event:`/`data:` 行は `json.dumps` が `\n` 等にエスケープするため、イベント境界（`\n\n`）やフィールド行に注入されない。改行・CRLF・`event:`・`data:` を仕込んだ本文で、`event:`/`data:` が各1本に保たれ本文がJSONで完全復元することを実測。
- 補足: 本文の抽出プロンプト側も、区切り文字 `POST_OPEN/CLOSE` を本文内で無効化しており（`text_user_prompt`）、プロンプトの囲いからの脱出も防いでいる（カテゴリ11関連）。

## 未検証

- 切断時に診断パイプラインの内部タスクが確実にキャンセルされるか（重い実診断中に切断して、モデル呼び出しが止まるか・リソースが解放されるか）は未確認。実VLM接続時に、長い診断を途中切断してサーバログを追うと確実。
