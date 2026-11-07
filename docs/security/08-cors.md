# CORS（カテゴリ8）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 実施日: 2026-11-06 / ローカル実施・破壊的操作なし
- 環境: 本番モード(:8001)。`Origin` ヘッダを付けてプリフライト・実リクエストを送信

## 判定

脆弱性なし。許可Originにだけ `Access-Control-Allow-Origin` を返し、任意Originは反射しない。

## 結果

| # | テスト | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| 反射 | `Origin: https://evil.example` プリフライト | ACAOを返さない | `allow-credentials:true` は出るが **ACAOなし** | 合格 |
| 反射 | `Origin: https://evil.example` 実GET | ACAOを返さない | **ACAOなし** | 合格 |
| 許可 | `Origin: http://localhost:3000` | ACAO返却 | `access-control-allow-origin: http://localhost:3000` | 合格 |

## 所見

- `CORSMiddleware` は `allow_origins=["http://localhost:3000"]`・`allow_credentials=True`。
- `evil.example` にも `Access-Control-Allow-Credentials: true` や許可メソッド一覧は返るが、**肝心の `Access-Control-Allow-Origin` は許可Originにしか返らない**。ACAOが無ければブラウザは資格情報付きクロスオリジン読み取りを許可しないため、悪用はできない。これはStarletteのCORSの標準挙動で、設定は正しい。
- 注意: `allow_origins` はワイルドカード（`*`）ではなく明示リスト。本番公開時は、公開するフロントのオリジンを `cors_origins` に設定すること。`*` と `allow_credentials=True` の併用は禁止（Starletteが弾くが、設定として入れない）。
