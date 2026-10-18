# Hack Day 前に作成したもの

README の「HackDay以前に作成したもの」はここから書く。

| 日付 | 内容 | 場所 |
|---|---|---|
| 2026-10-19 | リポジトリの基本設定（.gitignore、.editorconfig、.env.example、gitleaks の設定、Makefile の枠、Node と Python のバージョン固定） | ルート |
| 2026-10-19 | 各フォルダの README（engine は当日実装である旨のみ） | engine/、data-prep/、eval/ |
| 2026-10-19 | 手がかりの形式（Pydantic モデル）と、固定の手がかりを返すモック API（`POST /api/detect`、`GET /health`）。写真は本文で受け取りメモリ上だけで扱う。モック以外では 501 を返す | api/ |
| 2026-10-19 | uv ワークスペース、ruff・mypy・pytest の設定、`make dev-api` | ルートの pyproject.toml、Makefile |
| 2026-10-19 | モデル呼び出しのクライアント（vLLM の OpenAI 互換 API、PP-OCRv5 の HTTP サービス）。応答をそのまま返すだけで、手がかりの形式への変換は含まない。第三者の AI サービスへの送信を拒否する確認 | detect/ |
