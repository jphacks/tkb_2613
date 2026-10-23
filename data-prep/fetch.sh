#!/usr/bin/env bash
# 公開データを data-prep/raw/ に取得する。取得済みのファイルは取り直さない。
# e-Stat の地域メッシュ統計はブラウザでの取得が必要なので、なければ置き場所を案内して止まる。
set -euo pipefail

RAW="$(cd "$(dirname "$0")" && pwd)/raw"

JAPANPOST_URL="https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip"
STAT_MESH_URL="https://www.stat.go.jp/data/mesh/csv"
KSJ_N02_URL="https://nlftp.mlit.go.jp/ksj/gml/data/N02/N02-24/N02-24_GML.zip"
PREFECTURES=(11 12 13 14)

if ! compgen -G "$RAW/estat/*.zip" >/dev/null; then
  cat >&2 <<EOF
e-Stat の地域メッシュ統計がありません。
  令和2年国勢調査 4次メッシュ（500m）「人口及び世帯」の zip を
  $RAW/estat/
  に置いてから、もう一度 make data を実行してください。手順は data-prep/README.md にあります。
EOF
  exit 1
fi

fetch() {
  local url="$1" dest="$2"
  if [[ -s "$dest" ]]; then
    echo "取得済み: ${dest#"$RAW"/}"
    return
  fi
  mkdir -p "$(dirname "$dest")"
  echo "取得中:   $url"
  curl --fail --silent --show-error --location --retry 3 --output "$dest.part" "$url"
  mv "$dest.part" "$dest"
}

fetch "$JAPANPOST_URL" "$RAW/japanpost/utf_ken_all.zip"
for pref in "${PREFECTURES[@]}"; do
  fetch "$STAT_MESH_URL/$pref.csv" "$RAW/stat_mesh/$pref.csv"
done
fetch "$KSJ_N02_URL" "$RAW/ksj/N02-24_GML.zip"
