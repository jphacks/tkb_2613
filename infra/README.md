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
make up                # docker compose -f infra/docker-compose.yml up --build
make down
```

- web と api だけを動かす。VLM と OCR はチームのサーバーで動かし、`.env` の `VLM_BASE_URL`、`OCR_BASE_URL` で指定する
- 既定は `MOCK_MODE=1`（外部に一切接続しない）。実際のモデルにつなぐときは `.env` で `MOCK_MODE=0` にする
- コンテナのファイルシステムは読み取り専用（写真をディスクに残さないため）。書き込めるのはメモリ上の `/tmp` だけ
- ポートは `127.0.0.1` にだけ公開する
- 画面は `/api` を api に中継する（`web/next.config.ts` の rewrites）。中継先の `API_ORIGIN` はビルド時に読まれるので、変えたら `make up` でビルドし直す
