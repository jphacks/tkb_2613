# ビルドコンテキストはリポジトリのルート（uv ワークスペースのため）
#   docker build -f api/Dockerfile .

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# 依存関係だけを先に入れて、ソース変更時のキャッシュを効かせる
COPY pyproject.toml uv.lock ./
COPY api/pyproject.toml api/
COPY detect/pyproject.toml detect/
RUN uv sync --frozen --no-dev --package tkb-api --no-install-workspace

COPY api api
COPY detect detect
RUN uv sync --frozen --no-dev --package tkb-api --no-editable


FROM python:3.13-slim
RUN useradd --system --no-create-home app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER app
EXPOSE 8001
CMD ["uvicorn", "tkb_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
