# infra

## 必要なもの

| ツール | バージョン |
|---|---|
| Node.js | 24（`.nvmrc`） |
| pnpm | 11 |
| uv | 0.13 以上（Python 3.13 は `uv python install 3.13`） |
| Docker / Compose | Docker Desktop の場合は WSL 連携をオンにする |
| gitleaks | 8 |

## ローカルで起動（開発用、モックモード）

```bash
cp .env.example .env   # 初回だけ
make setup
make dev               # web: http://localhost:3000 / api: http://localhost:8001
```

## Docker Compose で起動

```bash
make up                # docker compose --env-file .env -f infra/docker-compose.yml up --build
make down
```

- web と api だけを動かす。VLM と OCR はチームのサーバーで動かし、`.env` の `VLM_BASE_URL`、`OCR_BASE_URL` で指定する
- api の設定（`MOCK_MODE`、`CORS_ORIGINS`、`COOKIE_SECURE` など）はリポジトリ直下の `.env` から読む。`.env` に書いていない項目は既定値（モック、CORS は `http://localhost:3000`、Cookie の Secure なし）。実際のモデルにつなぐときは `.env` で `MOCK_MODE=0` にする
- `make up` は compose の変数（`WEB_BIND`）も `.env` から読む。`docker compose` を直接使うときは `--env-file .env` を付ける
- コンテナのファイルシステムは読み取り専用。本人が明示的に作った閲覧リンクの結果だけ、API の `shared-results` ボリュームに2時間保存する。投稿の画像バイト列は保存しない
- ポートは既定で `127.0.0.1` にだけ公開する。api（8001）はどの環境でも `127.0.0.1` のまま
- 画面は `/api` を api に中継する（`web/next.config.ts` の rewrites）。中継先の `API_ORIGIN` はビルド時に読まれるので、変えたら `make up` でビルドし直す

## AWS のアプリの EC2 で起動（一般公開）

構成と理由は [docs/aws-migration.md](../docs/aws-migration.md)。EC2 はプライベートサブネットに置き、入口は CloudFront（VPC origin）だけにする。

```bash
cp infra/aws.env.example .env   # <...> を埋める。キーは書かない
make up
```

| 項目 | 手元（既定） | AWS のアプリの EC2 | 理由 |
|---|---|---|---|
| `MOCK_MODE` | 1 | 0 | 実際の Bluesky とモデルにつなぐ |
| `WEB_BIND` | `127.0.0.1` | `0.0.0.0` | CloudFront の VPC origin から web（3000）に届くようにする。届く先はセキュリティグループで VPC origin だけに絞る |
| `COOKIE_SECURE` | 0 | 1 | HTTPS で公開するので Cookie を HTTPS だけで送る（検査 2 の指摘） |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | `["https://<配信ID>.cloudfront.net"]` | 公開する画面のオリジンだけを許可する（検査 8） |
| `VLM_BASE_URL`・`OCR_BASE_URL` | 手元か RunPod | GPU のプライベート IP | GPU はインターネットから届かない |
| `MODEL_ALLOWED_HOST_SUFFIXES` | 空（localhost だけ） | GPU のプライベート IP | 送り先の許可リスト。IP は完全一致 |
| `VLM_API_KEY` | `.env` | Secrets Manager から起動時に渡す | キーをファイルに残さない |
| `SHARE_ENABLED` | （未実装） | 0 | 公開中は閲覧リンクの機能をオフにする。api と画面への実装は別の PR |

- api の 8001 番は `127.0.0.1` のままにする。外から届くのは web だけで、api は compose のネットワークの中で web から呼ばれる
- `.env` の値に `$` が入る場合は `'...'` で囲む（compose が変数として展開しないように）
