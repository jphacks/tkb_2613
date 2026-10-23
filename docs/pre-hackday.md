# Hack Day 前に作成したもの

README の「HackDay以前に作成したもの」はここから書く。

| 日付 | 内容 | 場所 |
|---|---|---|
| 2026-10-19 | リポジトリの基本設定（.gitignore、.editorconfig、.env.example、gitleaks の設定、Makefile の枠、Node と Python のバージョン固定） | ルート |
| 2026-10-19 | 各フォルダの README（engine は当日実装である旨のみ） | engine/、data-prep/、eval/ |
| 2026-10-19 | 手がかりの形式（Pydantic モデル）と、固定の手がかりを返すモック API（`POST /api/detect`、`GET /health`）。写真は本文で受け取りメモリ上だけで扱う。モック以外では 501 を返す | api/ |
| 2026-10-19 | uv ワークスペース、ruff・mypy・pytest の設定、`make dev-api` | ルートの pyproject.toml、Makefile |
| 2026-10-19 | 画面の骨組み：写真の選択と、結果表示の枠（写真の上に手がかりの位置を重ねる、一覧）。手がかりの型（TypeScript）、api を呼ぶクライアント、vitest の設定、`make dev`（web と api を同時に起動） | web/、Makefile |
| 2026-10-19 | Dockerfile（api、web）と Docker Compose、起動手順。コンテナは読み取り専用、ポートは 127.0.0.1 のみ、`make up` / `make down` | api/Dockerfile、web/Dockerfile、infra/ |
| 2026-10-19 | CI（GitHub Actions）：Python の lint・型・テスト、web の lint・型・テスト・ビルド、Docker イメージのビルド、gitleaks。action はコミットの SHA で固定 | .github/workflows/ci.yml |
| 2026-10-19 | モデル呼び出しのクライアント（vLLM の OpenAI 互換 API、PP-OCRv5 の HTTP サービス）。応答をそのまま返すだけで、手がかりの形式への変換は含まない。第三者の AI サービスへの送信を拒否する確認 | detect/ |
| 2026-10-23 | メンバー向けの環境構築手順書（Mac と Windows〈WSL2〉の手順、動作確認、よくあるつまずき） | docs/setup.md |
| 2026-10-23 | 公開データの取得と表への変換（1都3県）。`make data` で郵便番号・市区町村別メッシュ・鉄道データ（N02）を取得し、e-Stat の地域メッシュ統計と合わせて、市区町村と 1km メッシュ、500m メッシュの世帯数・人口、郵便番号、駅、市外局番の 5 つの表を Parquet で書き出す。表を使った計算（絞り込み、世帯数の計算、徒歩圏の判定）は含まない | data-prep/、Makefile |
| 2026-10-23 | 市外局番と市区町村の対応表（総務省「市外局番の一覧」から 1都3県を含む 51 行を写したもの） | data-prep/manual/area_codes.csv |
