#!/bin/bash
# EC2 の systemd から実行する。秘密は stdout・ディスクに書かず /run (tmpfs) に短時間だけ置く。
set -euo pipefail
cd /opt/tkb_2613
if [ ! -f .env ]; then
  echo ".env がありません。infra/terraform/README.md を参照してください" >&2
  exit 1
fi
umask 077
install -d -m 700 /run/tkb_2613
trap 'rm -f /run/tkb_2613/api-secrets.env /run/tkb_2613/web-secrets.env' EXIT
key="$(aws secretsmanager get-secret-value --region us-east-1 --secret-id tkb_2613/vlm-api-key --query SecretString --output text)"
x_client_secret=""
# X を有効にする前は Secret の入れ物だけで値がないため、取得失敗は空のまま起動する。
if fetched_x_secret="$(aws secretsmanager get-secret-value --region us-east-1 --secret-id tkb_2613/x-client-secret --query SecretString --output text 2>/dev/null)"; then
  x_client_secret="$fetched_x_secret"
fi
internal="$(openssl rand -hex 32)"
printf 'VLM_API_KEY=%s\nX_CLIENT_SECRET=%s\nINTERNAL_AUTH_SECRET=%s\n' "$key" "$x_client_secret" "$internal" > /run/tkb_2613/api-secrets.env
printf 'INTERNAL_AUTH_SECRET=%s\n' "$internal" > /run/tkb_2613/web-secrets.env
unset key x_client_secret fetched_x_secret internal
docker compose --env-file .env -f infra/docker-compose.yml up --build -d
