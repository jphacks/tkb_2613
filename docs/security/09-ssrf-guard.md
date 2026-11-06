# SSRF・取得先/送信先ガード（カテゴリ9）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 状態: **未実施**

## 予定している確認

- 画像取得先が cdn.bsky.app 以外 / 非https / メタデータIP / リダイレクトを拒否するか
- ensure_team_endpoint（拒否リスト方式）の穴
- プロンプトインジェクションの設計確認（静的）
