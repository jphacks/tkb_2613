# ビルドコンテキストはリポジトリのルート（uv ワークスペースのため）
#   docker build -f api/Dockerfile .

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# 依存関係だけを先に入れて、ソース変更時のキャッシュを効かせる
COPY pyproject.toml uv.lock ./
COPY common/pyproject.toml common/
COPY api/pyproject.toml api/
COPY detect/pyproject.toml detect/
COPY engine/pyproject.toml engine/
# ワークスペースの解決に必要なだけで、api のイメージには入れない
COPY data-prep/pyproject.toml data-prep/
RUN uv sync --frozen --no-dev --package tkb-api --no-install-workspace

COPY common common
COPY api api
COPY detect detect
COPY engine engine
RUN uv sync --frozen --no-dev --package tkb-api --no-editable


FROM python:3.13-slim
RUN useradd --system --no-create-home app
COPY --from=build /app/.venv /app/.venv
# MOCK_MODE の診断で流す架空のデモ用アカウントの投稿（写真本体は含まない）
COPY eval/fixtures/demo_observations.json /app/eval/fixtures/
# 推理の表（data/processed）はコミットしないのでイメージに入れない。
# docker compose で読み取り専用でつなぐ（infra/docker-compose.yml）。なければ最寄り駅のルールを飛ばす
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER app
EXPOSE 8001
CMD ["uvicorn", "tkb_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
