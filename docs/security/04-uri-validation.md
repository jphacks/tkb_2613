# 削除対象の正当性・at:// URI検証（カテゴリ4）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 実施日: 2026-11-06 / ローカル実施・破壊的操作なし（実削除なし）
- 環境: `is_own_post_uri` と `delete_own_posts` の関数単体検証（モックHTTP削除は本番ガードを通らないため、関数直呼びで精密に確認）。`delete_own_posts` にはモックclientを渡し、どのURIが `client.delete_post` に渡るかを観測

## 判定

脆弱性なし（他人・別種類・パス小細工はすべて拒否）。関数単体の堅牢化として Low 指摘1点（rkey の文字種を見ていない）。

## 結果

`is_own_post_uri(uri, 本人DID)` の戻り値：

| テスト | 入力 rkey/形 | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| 正規（自分） | `.../app.bsky.feed.post/3kabc` | True | True | 合格 |
| 他人のDID | `at://他人DID/.../3kabc` | False | False | 合格 |
| パストラバーサル | `.../post/3k/../3x`（literal `/`） | False | False | 合格 |
| コレクション偽装 | `.../app.bsky.feed.like/3kabc` | False | False | 合格 |
| 前方一致悪用 | `.../app.bsky.feed.post.evil/3kabc` | False | False | 合格 |
| rkey 空 | `.../app.bsky.feed.post/` | False | False | 合格 |
| rkey に `/` | `.../post/a/b` | False | False | 合格 |
| URLエンコード `..` | `.../post/%2e%2e%2f3x` | False 望ましい | **True** | 🟡 Low |
| 制御文字 | `.../post/a\nb` | False 望ましい | **True** | 🟡 Low |

`delete_own_posts`（モックclient）：

| テスト | 送ったID群 | `delete_post` に渡ったID | 判定 |
|---|---|---|---|
| 混在 | 本人正当 / 他人DID / like / `/`入り | **本人正当のみ** | 合格 |

## 所見

- `is_own_post_uri` は「`at://<本人DID>/app.bsky.feed.post/` で始まり、rkey が空でなく `/` を含まない」を要求。他人DID・`..`経路（literal）・別コレクション・接頭辞偽装・空rkey はすべて拒否。
- `delete_own_posts` は各IDを `is_own_post_uri` に通し、本人の正当URIだけを `client.delete_post` に渡す。他人DIDや別種類は渡らない。
- URIの DID は必ずログイン中の本人に固定され、さらにルート側が `known`（その診断に出た投稿ID）と照合する**二段構え**。片方が破られても他人の投稿削除は成立しない。

## 🟡 Low 指摘（実害なし・堅牢化推奨）

`is_own_post_uri`（[api/src/tkb_api/bluesky.py](../../api/src/tkb_api/bluesky.py)）は rkey の文字種を見ていないため、`%2e%2e%2f3x`（`../` のURLエンコード）や改行入りの rkey が `True` を返す。

- **実害はない**: DIDが本人固定のうえ、ルートが診断リストと照合するため、診断に無いこの種のIDは422で弾かれ、`delete_post` には到達しない。
- **推奨**: rkey を AT URI のレコードキー文字種（例 `^[A-Za-z0-9._~-]+$`）で検証すると、docstring の意図どおり関数単体でも不正形式を弾ける。
