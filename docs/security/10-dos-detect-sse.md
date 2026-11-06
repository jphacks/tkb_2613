# 認証不要EP・サイズ上限・SSE 耐性（カテゴリ10）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 状態: **未実施**

## 予定している確認

- /api/detect: 20MiB超で413・許可外415・空body400・本番501
- 認証不要EPが無制限の入口にならないか
- SSE の途中切断でサーバが回り続けないか・keep-alive
