# 入力検証（カテゴリ5）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 状態: **未実施**

## 予定している確認

- /api/session: 空body・欠落・未知フィールド(extra=forbid)・巨大handle
- /api/delete: 0件・上限超・重複・512字超・型違い
- /api/simulate: 上限超・型違い
- Content-Type 誤り
