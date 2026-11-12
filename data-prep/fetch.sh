#!/usr/bin/env bash
# 公開データを data-prep/raw/ に取得する。取得済みのファイルは取り直さない。
# e-Stat の地域メッシュ統計はブラウザでの取得が必要なので、なければ置き場所を案内して止まる。
set -euo pipefail

RAW="$(cd "$(dirname "$0")" && pwd)/raw"

JAPANPOST_URL="https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip"
STAT_MESH_URL="https://www.stat.go.jp/data/mesh/csv"
KSJ_N02_URL="https://nlftp.mlit.go.jp/ksj/gml/data/N02/N02-24/N02-24_GML.zip"
# 文部科学省「学校コード」（令和8年5月1日時点・暫定版）。東日本の学校（2つに分かれている）と大学等
MEXT_URLS=(
  "https://www.mext.go.jp/content/20260825-mxt_chousa01-000011635_2-1.csv"
  "https://www.mext.go.jp/content/20260825-mxt_chousa01-000011635_2-2.csv"
  "https://www.mext.go.jp/content/20260825-mxt_chousa01-000011635_6.csv"
)
# 国土数値情報「バス停留所（P11）」令和4年度版（平成22年度版は非商用なので使わない）
KSJ_P11_URL="https://nlftp.mlit.go.jp/ksj/gml/data/P11/P11-22"
# 国土数値情報「行政区域（N03）」2026年1月1日時点（バス停がどの区市町村にあるかを引く）
KSJ_N03_URL="https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026"
# 国土地理院「指定緊急避難場所・指定避難所データ」の都道府県別 CSV（_2 が指定緊急避難場所、_1 が指定避難所）
GSI_SHELTER_URL="https://hinanmap.gsi.go.jp/hinanjocp/defaultFtpData/csv"
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

if ! compgen -G "$RAW/houjin/*.zip" >/dev/null; then
  cat >&2 <<EOF
法人番号の全件データがないので、法人の表（corporations.sqlite）は作らずに進みます。
  作るときは、法人番号公表サイトの「全件データ」から CSV 形式・Shift-JIS の
  埼玉・千葉・東京・神奈川の zip を落とし、展開せずに
  $RAW/houjin/
  に置いてから、もう一度 make data を実行してください。手順は data-prep/README.md にあります。
EOF
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
for url in "${MEXT_URLS[@]}"; do
  fetch "$url" "$RAW/mext/$(basename "$url")"
done
for pref in "${PREFECTURES[@]}"; do
  for kind in 1 2; do
    fetch "$GSI_SHELTER_URL/${pref}000_${kind}.csv" "$RAW/gsi/${pref}000_${kind}.csv"
  done
done
for pref in "${PREFECTURES[@]}"; do
  fetch "$KSJ_P11_URL/P11-22_${pref}_SHP.zip" "$RAW/ksj/P11-22_${pref}_SHP.zip"
  fetch "$KSJ_N03_URL/N03-20260101_${pref}_GML.zip" "$RAW/ksj/N03-20260101_${pref}_GML.zip"
done
