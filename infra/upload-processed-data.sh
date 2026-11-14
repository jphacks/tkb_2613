#!/bin/bash
# 手元で実行する（人が行う）。make data で作った data/processed を tar で固めて S3 に上げ、
# 短い期限の署名付き URL を出す。EC2 側は infra/install-processed-data.sh でこの URL から取る。
# EC2 には S3 の権限を足さない（署名付き URL を HTTPS で取るだけ）。手順は infra/terraform/README.md。
#
#   infra/upload-processed-data.sh <バケット名> [URL の有効期限の秒数（既定 900、60〜3600）]
#
# - 法人番号の SQLite（データ準備で手で置く zip から作る）と、e-Stat のメッシュ統計（ブラウザで取得）
#   から作った households_500m.parquet も含める。どれか1つでも欠けていたら上げない
# - 写真場所のPOI索引 places.sqlite3（P05 などの取込で作る）は任意。$SRC 直下になければ
#   $SRC/national/places.sqlite3 を使い、tar では直下に置く（本番の api は data/processed の表を
#   選ぶので、索引も直下にないと使われない）
# - バケットは公開アクセスを全部ブロックしたものだけを使う（違えば止まる）
# - 署名付き URL は、期限内なら誰でも取れる。チャットや Issue に貼らず、SSM のセッションにだけ貼る
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${TKB_PROCESSED_DIR:-$ROOT/data/processed}"
BUCKET="${1:?使い方: $0 <バケット名> [有効期限の秒数]}"
EXPIRES="${2:-900}"
PREFIX="processed"
# api が読む表（engine/src/tkb_engine/gazetteer.py）と、e-Stat から作る世帯数の表
REQUIRED=(
  stations.parquet postal.parquet area_codes.parquet muni_mesh.parquet households_500m.parquet
  schools.parquet shelters.parquet bus_stops.parquet school_districts.parquet ridership.parquet
  corporations.sqlite
)

if [[ ! "$EXPIRES" =~ ^[0-9]+$ ]] || ((EXPIRES < 60 || EXPIRES > 3600)); then
  echo "有効期限は 60〜3600 秒にしてください（指定：$EXPIRES）" >&2
  exit 1
fi
missing=()
for f in "${REQUIRED[@]}"; do
  [ -s "$SRC/$f" ] || missing+=("$f")
done
if ((${#missing[@]})); then
  echo "$SRC に次の表がありません：${missing[*]}" >&2
  echo "make data をやり直してください（法人番号の zip と e-Stat の zip は data-prep/README.md の手順で手で置く）" >&2
  exit 1
fi
# 任意：写真場所のPOI索引。なければ写真場所の候補はいつも「不明」になる
PLACES_DIR=""
if [ -s "$SRC/places.sqlite3" ]; then
  PLACES_DIR="$SRC"
elif [ -s "$SRC/national/places.sqlite3" ]; then
  PLACES_DIR="$SRC/national"
fi

block="$(aws s3api get-public-access-block --bucket "$BUCKET" \
  --query '[PublicAccessBlockConfiguration.BlockPublicAcls,PublicAccessBlockConfiguration.IgnorePublicAcls,PublicAccessBlockConfiguration.BlockPublicPolicy,PublicAccessBlockConfiguration.RestrictPublicBuckets]' \
  --output text)"
if [ "$(tr -s '[:space:]' ' ' <<<"$block" | sed 's/ $//')" != "True True True True" ]; then
  echo "バケット $BUCKET の公開アクセスのブロックが全部オンになっていません。上げずに止めます" >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="processed-$STAMP.tar.gz"
(cd "$SRC" && sha256sum "${REQUIRED[@]}" >"$WORK/MANIFEST.sha256")
PLACES_ARGS=()
if [ -n "$PLACES_DIR" ]; then
  (cd "$PLACES_DIR" && sha256sum places.sqlite3 >>"$WORK/MANIFEST.sha256")
  PLACES_ARGS=(-C "$PLACES_DIR" places.sqlite3)
fi
tar -czf "$WORK/$NAME" --owner=0 --group=0 --numeric-owner \
  -C "$SRC" "${REQUIRED[@]}" "${PLACES_ARGS[@]}" -C "$WORK" MANIFEST.sha256
SHA="$(sha256sum "$WORK/$NAME" | cut -d' ' -f1)"

KEY="$PREFIX/$NAME"
aws s3 cp --only-show-errors --sse AES256 "$WORK/$NAME" "s3://$BUCKET/$KEY"
URL="$(aws s3 presign "s3://$BUCKET/$KEY" --expires-in "$EXPIRES")"

cat <<MSG
上げました：s3://$BUCKET/$KEY（$(du -h "$WORK/$NAME" | cut -f1)）
写真場所のPOI索引：$(if [ -n "$PLACES_DIR" ]; then echo "入れました（$PLACES_DIR/places.sqlite3）"; else echo "なし（写真場所の候補は不明になります）"; fi)
tar の sha256：$SHA

アプリの EC2（SSM のセッション、root）で次を実行し、聞かれたら下の URL を貼る（$EXPIRES 秒で切れる）：
  /opt/tkb_2613/infra/install-processed-data.sh $SHA

署名付き URL（チャットや Issue に貼らない）：
$URL

届けたら、手元で消す：aws s3 rm s3://$BUCKET/$KEY
MSG
