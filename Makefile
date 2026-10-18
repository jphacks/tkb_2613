.DEFAULT_GOAL := help
.PHONY: help setup dev dev-api test lint secrets

help: ## コマンド一覧
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

setup: ## 依存関係のインストール
	@test ! -f pyproject.toml || uv sync --all-packages
	@test ! -d web || pnpm -C web install

dev: ## web と api をローカルで起動（モックモード）
	$(MAKE) dev-api

dev-api: ## api だけを起動（http://localhost:8001）
	MOCK_MODE=1 uv run uvicorn tkb_api.main:app --reload --port 8001

test: ## テスト
	@test ! -f pyproject.toml || uv run pytest
	@test ! -d web || pnpm -C web test

lint: ## lint と型チェック
	@test ! -f pyproject.toml || (uv run ruff check . && uv run ruff format --check . && uv run mypy)
	@test ! -d web || (pnpm -C web lint && pnpm -C web typecheck)

secrets: ## gitleaks で秘密情報を検査
	gitleaks git --config .gitleaks.toml --redact --verbose .
