# 入力検証（カテゴリ5）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 実施日: 2026-11-06 / ローカル実施・破壊的操作なし
- 環境: `/api/session` は本番モード(:8001)。ログインが要る `/api/delete`・`/api/simulate` はモック(:8002, `MOCK_MODE=1`)

## 判定

脆弱性なし。全リクエストモデルが `extra="forbid"`。不正入力はすべて422で、送信値の反射なし。

## 結果

`/api/session`：

| テスト | 送った内容 | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| 空body | `{}` | 422 | 422（handle required） | 合格 |
| handle欠落 | `{"handle":"a"}` | 422 | 422（password required） | 合格 |
| handle空 | `{"handle":"","password":"x"}` | 422 | 422（min_length） | 合格 |
| 未知フィールド | `{...,"admin":true}` | 422 | 422（Extra inputs not permitted） | 合格 |
| password空 | `{"handle":"a","password":""}` | 422 | 422（Value error） | 合格 |
| 非JSON | `notjson` | 422 | 422（JSON decode error） | 合格 |
| 型違いCT | `Content-Type: text/plain` + JSON | 4xx | 422 | 合格 |

`/api/delete`（上限10・min1）・`/api/simulate`：

| テスト | 送った内容 | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| 0件 | `{"delete":[]}` | 422 | 422（min_length） | 合格 |
| 上限超 | 11件 | 422 | 422（max_length） | 合格 |
| 文字列 | `{"delete":"x"}` | 422 | 422 | 合格 |
| 要素型違い | `{"delete":[1]}` | 422 | 422 | 合格 |
| 未知フィールド | `{"delete":["x"],"x":1}` | 422 | 422 | 合格 |

## 所見

- `SessionRequest` / `DeleteRequest` / `SimulateRequest` はすべて `model_config = ConfigDict(frozen=True, extra="forbid")`。未知フィールドは422で拒否。
- handle は `min_length=1, max_length=253`、正規化で前後空白と先頭 `@` を除去。password は空を `field_validator` で拒否（`SecretStr` のため repr・エラーに値が出ない）。
- `delete` は要素 `min_length=1, max_length=512`、配列 `min_length=1, max_length=10`（simulate は最大100）。
- 422応答の情報漏えいは [06-info-leak.md](06-info-leak.md) を参照。
