#!/bin/bash
# アプリの EC2 で root で実行する（人が行う）。infra/upload-processed-data.sh が出した署名付き URL から
# data/processed の tar を取り、sha256 と中身を確かめてから入れ替え、tkb-app を再起動する。
# EC2 のロールに S3 の権限はいらない（NAT 経由の HTTPS で取るだけ）。手順は infra/terraform/README.md。
#
#   /opt/tkb_2613/infra/install-processed-data.sh <tar の sha256>
#   （URL は聞かれたら貼る。画面とシェルの履歴に残さないため、引数では受け取らない）
#
# 前の表は data/processed.prev に残す。戻すときは README の「表を戻す」。
set -euo pipefail

APP_DIR="${TKB_APP_DIR:-/opt/tkb_2613}"
DEST="$APP_DIR/data/processed"
SHA="${1:?使い方: $0 <tar の sha256>}"
REQUIRED=(
  stations.parquet postal.parquet area_codes.parquet muni_mesh.parquet households_500m.parquet
  schools.parquet shelters.parquet bus_stops.parquet school_districts.parquet ridership.parquet
  corporations.sqlite
)

fail() {
  echo "$1" >&2
  exit 1
}

[[ "$SHA" =~ ^[0-9a-f]{64}$ ]] || fail "sha256 は 64 桁の16進数で渡してください"
read -rs -p "署名付き URL: " URL
echo
[[ "$URL" =~ ^https://[a-z0-9.-]+\.amazonaws\.com/ ]] || fail "S3 の https の URL ではありません"

install -d -m 755 "$APP_DIR/data"
# 入れ替えを mv だけで済ませるため、作業場所は同じファイルシステム（data/ の下）に作る
WORK="$(mktemp -d "$APP_DIR/data/.processed-XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
# curl は失敗しても URL を表示しない（-sS は状態コードだけ出す）
curl -fsS --proto '=https' --max-time 900 -o "$WORK/processed.tar.gz" "$URL" ||
  fail "取得できませんでした。URL の期限（既定 15 分）が切れていたら、手元でもう一度上げてください"
unset URL
echo "$SHA  $WORK/processed.tar.gz" | sha256sum -c --quiet - || fail "sha256 が合いません。入れ替えません"

# 中身は、名前が決まった普通のファイルだけ（ディレクトリ・リンク・../ を含むものは入れない）
while read -r mode _ _ _ _ name rest; do
  [ -z "$rest" ] || fail "tar に想定外の名前があります"
  [[ "$mode" == -* ]] || fail "tar に普通のファイル以外が入っています：$name"
  [[ "$name" =~ ^[a-z0-9_]+\.(parquet|sqlite)$|^MANIFEST\.sha256$ ]] || fail "tar に想定外の名前があります：$name"
done < <(tar -tvzf "$WORK/processed.tar.gz" --numeric-owner)

NEW="$WORK/processed"
mkdir "$NEW"
tar -xzf "$WORK/processed.tar.gz" -C "$NEW" --no-same-owner --no-same-permissions
for f in "${REQUIRED[@]}"; do
  [ -s "$NEW/$f" ] || fail "tar に $f がありません。入れ替えません"
done
(cd "$NEW" && sha256sum -c --quiet MANIFEST.sha256) || fail "表の sha256 が合いません。入れ替えません"
rm "$NEW/MANIFEST.sha256"
# api のコンテナは root ではない利用者で動くので、読めるようにする
chmod 755 "$NEW"
chmod 644 "$NEW"/*

rm -rf "$DEST.prev"
if [ -e "$DEST" ]; then
  mv "$DEST" "$DEST.prev"
fi
mv "$NEW" "$DEST"
echo "入れ替えました：$DEST（前の表は $DEST.prev）"
ls -l "$DEST"

systemctl restart tkb-app
echo "tkb-app を再起動しました。infra/terraform/README.md の「表を届けたら確かめる」を行ってください"
