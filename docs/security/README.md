# セキュリティテスト 目次

みーつけた api（commit df27bac）のローカル実機テスト。カテゴリごとに独立した報告ファイルに分ける。
破壊的操作（本物の投稿削除）は行わない。

| # | カテゴリ | 状態 | 報告 |
|---|---|---|---|
| 1 | 認証境界（本人だけを通せているか） | 実施済み・脆弱性なし | [01-auth-boundary.md](01-auth-boundary.md) |
| 2 | セッション管理・Cookie属性 | 未実施 | [02-session.md](02-session.md) |
| 3 | 認可・IDOR（他人のアカウントを触れないか） | 未実施 | [03-authz-idor.md](03-authz-idor.md) |
| 4 | 削除対象の正当性（`at://` URI検証） | 未実施 | [04-uri-validation.md](04-uri-validation.md) |
| 5 | 入力検証（スキーマ・境界・未知フィールド） | 未実施 | [05-input-validation.md](05-input-validation.md) |
| 6 | エラー・ログの情報漏えい | 未実施 | [06-info-leak.md](06-info-leak.md) |
| 7 | キャッシュ・レスポンスヘッダ | 未実施 | [07-headers-cache.md](07-headers-cache.md) |
| 8 | CORS | 未実施 | [08-cors.md](08-cors.md) |
| 9 | SSRF・画像取得先/モデル送信先ガード | 未実施 | [09-ssrf-guard.md](09-ssrf-guard.md) |
| 10 | 認証不要エンドポイント・サイズ上限・SSE 耐性 | 未実施 | [10-dos-detect-sse.md](10-dos-detect-sse.md) |
