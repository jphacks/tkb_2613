# ビルドコンテキストは web/
#   docker build web

FROM node:24-slim AS deps
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile


FROM deps AS build
COPY . .
# NEXT_PUBLIC_ で始まる値はビルド時に埋め込まれる
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8001
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm build


FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
