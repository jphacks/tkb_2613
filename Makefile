.DEFAULT_GOAL := help
.PHONY: help setup dev dev-api dev-web up down test lint secrets data

help: ## コマンド一覧
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

setup: ## 依存関係のインストール
	@test ! -f pyproject.toml || uv sync --all-packages
	@test ! -d web || pnpm -C web install

dev: ## web と api をローカルで起動（モックモード）
	$(MAKE) -j2 dev-api dev-web

dev-api: ## api だけを起動（http://localhost:8001）
	MOCK_MODE=1 uv run uvicorn tkb_api.main:app --reload --port 8001

dev-web: ## web だけを起動（http://localhost:3000）
	pnpm -C web dev

up: ## Docker Compose で web と api を起動（モックモード）
	docker compose -f infra/docker-compose.yml up --build

down: ## Docker Compose を止める
	docker compose -f infra/docker-compose.yml down

test: ## テスト
	@test ! -f pyproject.toml || uv run pytest
	@test ! -d web || pnpm -C web test

lint: ## lint と型チェック
	@test ! -f pyproject.toml || (uv run ruff check . && uv run ruff format --check . && uv run mypy)
	@test ! -d web || (pnpm -C web lint && pnpm -C web typecheck)

secrets: ## gitleaks で秘密情報を検査
	gitleaks git --config .gitleaks.toml --redact --verbose .

data: ## 公開データの取得と変換（data/processed/ に Parquet で出力）
	data-prep/fetch.sh
	uv run python -m tkb_data_prep
