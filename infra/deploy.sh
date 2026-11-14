#!/bin/bash
# アプリの EC2 で、最新の main を本番に出す。GitHub Actions の「本番デプロイ」から
# SSM Run Command（ドキュメント tkb_2613-deploy）経由で root として実行される。手で実行してもよい。
#
#   deploy.sh <40桁のコミット SHA>
#
# 手順は infra/terraform/README.md の「既存 EC2 の起動スクリプト更新」と同じ：
# checkout → 起動スクリプトを入れ直す → systemctl restart tkb-app。
# .env・data/processed・eval/local は git の管理外なので checkout では変わらない。
# 秘密は起動スクリプトが毎回 Secrets Manager から読み、/run（メモリ）にだけ置く。
#
# 確かめること：api の healthcheck、web の応答、公開オリジンでの infra/prod_smoke.py。
# どれかが失敗したら、前のコミットに戻して起動し直す（ロールバック）。
#
# 最後に必ず1行「DEPLOY_RESULT=<結果> PREVIOUS=<前のSHA> TARGET=<SHA> CURRENT=<いまのSHA>」を出す。
# 終了コード：0 成功 / 2 引数の誤り / 3 別のデプロイが実行中 / 4 始める前の確認で中止（何も変えていない）/
#             10 失敗してロールバックした / 20 ロールバックも失敗した
set -euo pipefail

REPO_DIR="${TKB_REPO_DIR:-/opt/tkb_2613}"
LOCK_FILE="${TKB_DEPLOY_LOCK:-/run/lock/tkb_2613-deploy.lock}"
COMPOSE_PROJECT="tkb_2613"
API_CONTAINER="${COMPOSE_PROJECT}-api-1"
WEB_URL="http://127.0.0.1:3000"
# 起動を待つ上限（秒）。イメージのビルドは systemctl restart の中で終わるので、ここはコンテナの起動待ち
HEALTH_TIMEOUT_SECONDS="${TKB_HEALTH_TIMEOUT_SECONDS:-180}"
START_SCRIPT_DEST="${TKB_START_SCRIPT_DEST:-/usr/local/bin/tkb-app-start}"
# ロールバック用に残す前のイメージの組の数（古いものから消す）
KEEP_ROLLBACK_IMAGES=3

target="${1:-}"
previous=""
result="aborted"
smoke_script=""

log() { printf '[deploy %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

finish() {
  [[ -n "$smoke_script" ]] && rm -f "$smoke_script"
  local current
  current="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "DEPLOY_RESULT=${result} PREVIOUS=${previous:-unknown} TARGET=${target:-none} CURRENT=${current}"
}
trap finish EXIT

if [[ ! "$target" =~ ^[0-9a-f]{40}$ ]]; then
  log "コミット SHA（40桁の小文字16進）を1つ渡してください"
  result="invalid_argument"
  exit 2
fi

# 同じ EC2 で2つのデプロイを同時に動かさない（Actions の concurrency に加えて、手での実行も含めて止める）
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "別のデプロイが実行中です"
  result="locked"
  exit 3
fi

cd "$REPO_DIR"
previous="$(git rev-parse HEAD)"

abort() {
  log "$1"
  result="aborted"
  exit 4
}

[[ -f .env ]] || abort ".env がありません（infra/terraform/README.md の「アプリの .env を作る」）"
# 手で直した追跡ファイルがあれば、checkout で消さないように止める（.env などの管理外のファイルは見ない）
git diff --quiet HEAD -- || abort "追跡しているファイルに手元の変更があります。git status で確かめてください"

git fetch --quiet origin main
latest="$(git rev-parse origin/main)"
[[ "$latest" == "$target" ]] || abort "最新の main ではありません（main は ${latest}）"

public_url="$(sed -n 's/^PUBLIC_URL=//p' .env | tail -n 1)"
[[ "$public_url" == https://* ]] || abort ".env の PUBLIC_URL が https:// で始まっていません"

# 確かめるときは、ロールバックのあとも、デプロイするコミットの prod_smoke.py を使う
# （前のコミットの版は、応答の形が変わる前の古い判定のことがあるため）
smoke_script="$(mktemp)"
git show "${target}:infra/prod_smoke.py" > "$smoke_script" || abort "デプロイするコミットに infra/prod_smoke.py がありません"

# 前のイメージに名前を付けて残す（ロールバックで作り直せないときに、手で戻すため）
backup_tag="rollback-${previous:0:7}"
for service in api web; do
  if docker image inspect "${COMPOSE_PROJECT}-${service}:latest" >/dev/null 2>&1; then
    docker tag "${COMPOSE_PROJECT}-${service}:latest" "${COMPOSE_PROJECT}-${service}:${backup_tag}"
  fi
done
log "前のコミット ${previous:0:7} のイメージを :${backup_tag} として残しました"

# checkout → 起動スクリプトを入れ直す → 起動し直す（README の正式な手順）
start_at() {
  # if の中で呼ぶので set -e が効かない。1つでも失敗したらそこで止める
  git checkout --quiet --detach "$1" &&
    install -m 700 infra/tkb-app-start.sh "$START_SCRIPT_DEST" &&
    systemctl restart tkb-app
}

wait_for_api() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS)) state
  while ((SECONDS < deadline)); do
    state="$(docker inspect -f '{{.State.Health.Status}}' "$API_CONTAINER" 2>/dev/null || echo missing)"
    [[ "$state" == "healthy" ]] && return 0
    sleep 3
  done
  log "api が healthy になりません（最後の状態：${state}）"
  return 1
}

wait_for_web() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  while ((SECONDS < deadline)); do
    if curl -fsS -o /dev/null --max-time 5 "${WEB_URL}/" &&
      curl -fsS -o /dev/null --max-time 5 "${WEB_URL}/api/features"; then
      return 0
    fi
    sleep 3
  done
  log "web（/ と /api/features）が応答しません"
  return 1
}

verify() {
  wait_for_api || return 1
  log "api：healthy"
  wait_for_web || return 1
  log "web：/ と /api/features が 200"
  # 公開オリジン（CloudFront と WAF を通る）で、ログインなしの動作と遮断を確かめる
  python3 "$smoke_script" "$public_url" || {
    log "prod_smoke.py が失敗しました"
    return 1
  }
}

rollback() {
  log "前のコミット ${previous:0:7} に戻します"
  if start_at "$previous" && verify; then
    log "ロールバックしました。本番は ${previous:0:7} で動いています"
    result="rolled_back"
    exit 10
  fi
  log "ロールバックも失敗しました。手で戻す場合は :${backup_tag} のイメージを使えます（infra/terraform/README.md）"
  result="rollback_failed"
  exit 20
}

log "${previous:0:7} → ${target:0:7} をデプロイします"
if ! start_at "$target"; then
  log "起動できませんでした"
  rollback
fi
if ! verify; then
  rollback
fi

# ロールバック用のイメージは新しい組だけ残し、名前の外れたイメージを消す（ビルドのキャッシュは残す）
for service in api web; do
  docker image ls "${COMPOSE_PROJECT}-${service}" --format '{{.CreatedAt}}\t{{.Tag}}' |
    awk -F '\t' '$2 ~ /^rollback-/' | sort -r | tail -n +$((KEEP_ROLLBACK_IMAGES + 1)) | cut -f2 |
    while read -r tag; do docker rmi "${COMPOSE_PROJECT}-${service}:${tag}" >/dev/null || true; done
done
docker image prune -f >/dev/null || true
result="success"
log "デプロイしました：${target:0:7}"
