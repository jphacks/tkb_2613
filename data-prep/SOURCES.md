# 出典と利用条件

data-prep で使う公開データ。データ本体はリポジトリに含めない（`manual/area_codes.csv` を除く）。
作品の画面や発表資料でこれらのデータを使うときは、下の「出典の書き方」で出典を示す。

| データ | 提供元 | 取得元 | 利用条件 | 取得日 |
|---|---|---|---|---|
| 郵便番号データ（住所の郵便番号、1レコード1行、UTF-8形式） | 日本郵便株式会社 | https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip | 「郵便番号データに限っては日本郵便株式会社は著作権を主張しません。自由に配布していただいて結構です。」（[説明書](https://www.post.japanpost.jp/zipcode/dl/readme.html)） | 2026-10-23 |
| 市区町村別メッシュ・コード一覧（全国01〜47。関東向け既存処理は11〜14） | 総務省統計局 | https://www.stat.go.jp/data/mesh/csv/01.csv〜47.csv（都道府県別） | [統計局ホームページの利用ルール](https://www.stat.go.jp/info/riyou.html)（公共データ利用規約 第1.0版に準拠、CC BY 4.0 と互換） | 出典確認 2026-11-14。全国版を取得・生成済み（加工済みParquetはローカルignored出力） |
| 国土数値情報 鉄道データ（N02、2024年度） | 国土交通省 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2024.html | オープンデータ（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)） | 2026-10-23 |
| 令和2年国勢調査 地域メッシュ統計 4次メッシュ（500m）「人口及び世帯」 | 総務省統計局（政府統計の総合窓口 e-Stat） | https://www.e-stat.go.jp/gis （統計GIS のデータダウンロード。ブラウザで取得） | [e-Stat の利用規約](https://www.e-stat.go.jp/terms-of-use)（政府標準利用規約 第2.0版に準拠、CC BY 4.0 と互換） | 2026-10-23 |
| 学校コード（令和8年5月1日時点・暫定版、CSV） | 文部科学省 | https://www.mext.go.jp/b_menu/toukei/mext_01087.html | [文部科学省ホームページの利用ルール](https://www.mext.go.jp/b_menu/1351168.htm)（公共データ利用規約 第1.0版に準拠、CC BY 4.0 と互換） | 2026-10-25 |
| 国土数値情報 バス停留所データ（P11、令和4年度版。平成22年度版は使わない） | 国土交通省 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P11-v3_0.html （`P11-22_{11..14}_SHP.zip`） | 「国土数値情報ダウンロードサイトコンテンツ利用規約」に基づく（オープンデータ）。平成22年度版は非商用なので取り込まない | 2026-11-12 |
| 国土数値情報 行政区域データ（N03、2026年1月1日時点） | 国土交通省 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html （`N03-20260101_{11..14}_GML.zip`） | オープンデータ（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)） | 2026-11-12 |
| 国土数値情報 駅別乗降客数データ（S12、2025年度整備版。2024年度までの乗降客数） | 国土交通省 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-S12-2024.html （`S12-25_GML.zip`、全国1ファイル） | オープンデータ（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)）。2024-07-05 の国土交通省の発表で、すべてのデータが商用利用可 | 2026-11-12 |
| 国土数値情報 小学校区データ（A27）・中学校区データ（A32）、令和3年度版 | 国土交通省 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A27-v3_0.html 、https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A32-v3_0.html （`A27-21_{11..14}_GML.zip`、`A32-21_{11..14}_GML.zip`） | 「各市町村の定めによる」。自治体ごとの条件は [R3_Terms_of_use_municipality_data.xlsx](https://nlftp.mlit.go.jp/ksj/gml/codelist/R3_Terms_of_use_municipality_data.xlsx) で、表の terms・note 列に残す。「再配布・再利用不可」（所沢市・東松山市）は取り込まない。「条件公開」（白岡市・川島町：地図データは参考情報とする）は条件を根拠に添えて取り込む。「商用利用不可」の自治体（小学校区で 20）も取り込む | 2026-11-12 |
| 指定緊急避難場所・指定避難所データ（都道府県別 CSV、11000〜14000 の `_1`・`_2`） | 国土地理院 | https://hinanmap.gsi.go.jp/hinanjocp/defaultFtpData/csv/13000_2.csv など（案内は https://www.gsi.go.jp/bousaichiri/hinanbasho.html ） | [国土地理院コンテンツ利用規約](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html)（公共データ利用規約 第1.0版。CC BY 4.0 と互換）と、ダウンロードサイトの「ご利用上の注意」（最新でない場合や未掲載の場合があること、第三者に提供するときはこの注意が伝わるようにすること） | 2026-11-12 |
| 法人番号公表サイト 基本3情報 全件データ（CSV 形式・Shift-JIS、埼玉・千葉・東京・神奈川） | 国税庁 | https://www.houjin-bangou.nta.go.jp/download/zenken/ （ブラウザで取得して `raw/houjin/` に置く） | [法人番号公表サイトの利用規約](https://www.houjin-bangou.nta.go.jp/riyokiyaku/index.html)（公共データ利用規約 第1.0版に準拠。CC BY 4.0 と互換） | 2026-11-12（2026-10-30 版） |
| ごみと資源の収集日（syusyubi.csv） | 文京区 | https://www.city.bunkyo.lg.jp/documents/6059/syusyubi.csv （案内は https://www.city.bunkyo.lg.jp/b004/p006286.html ） | 文京区オープンデータ（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)）。データの時点の記載はない（ファイルの更新は 2026-03-23） | 2026-11-12 |
| 市外局番の一覧（令和8年3月1日現在、Word 版） | 総務省 | https://www.soumu.go.jp/main_content/001072458.doc | [総務省ホームページの利用条件](https://www.soumu.go.jp/menu_kyotsuu/policy/tyosaku.html)（公共データ利用規約 第1.0版に準拠） | 2026-10-23 |
| 任意ローカルPOI名称索引（`places.sqlite3`。自動取得しない） | 利用者がローカルで準備するGeoJSONL。候補データ: Overture Maps Places | https://docs.overturemaps.org/guides/places/ | 2026-11時点のスキーマは `id,names,basic_category,taxonomy,addresses,sources`。sourceごとにライセンスが異なり、`sources[].license` が欠落する場合もある。`sources[].license` または確認済みのdataset別SPDX mappingを保持し、ライセンス不明の行は検索別名を作らない。[Attribution](https://docs.overturemaps.org/attribution/) と各provider条件を取得前に確認 | スキーマ確認 2026-11-14 |

## 出典の書き方

- 郵便番号データ：日本郵便株式会社「郵便番号データ」
- 出典：総務省統計局「市区町村別メッシュ・コード一覧」（https://www.stat.go.jp/data/mesh/m_itiran.html）を加工して作成
- 「国土数値情報（鉄道データ）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2024.html）を加工して作成
- 出典：政府統計の総合窓口（e-Stat）（https://www.e-stat.go.jp/）、総務省統計局「令和2年国勢調査 地域メッシュ統計」を加工して作成
- 出典：文部科学省「学校コード」（https://www.mext.go.jp/b_menu/toukei/mext_01087.html）を加工して作成
- 出典：総務省「市外局番の一覧」（https://www.soumu.go.jp/main_content/001072458.doc）を加工して作成
- 「国土数値情報（バス停留所データ）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P11-v3_0.html）を加工して作成。令和4年度（作成時点は概ね2022年8月）のデータ
- 「国土数値情報（行政区域データ）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html）を加工して作成
- 「国土数値情報（駅別乗降客数データ）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-S12-2024.html）を加工して作成
- 「国土数値情報（小学校区データ）」「国土数値情報（中学校区データ）」（国土交通省）（上の URL）を加工して作成。令和3年度のデータで、境界には推定による線や重なりがあり、公式な資料ではない
- 出典：国税庁法人番号公表サイト（国税庁）（https://www.houjin-bangou.nta.go.jp/download/zenken/）を加工して作成
- 「指定緊急避難場所データ」「指定避難所データ」（国土地理院）（https://www.gsi.go.jp/bousaichiri/hinanbasho.html）をもとに作成。最新でない場合や未掲載の場合があります（最新の状況は各市町村にご確認ください）

画面で避難所の表を根拠に出すときは、上の注記（最新でない場合や未掲載の場合があること）を必ず添える（`engine/src/tkb_engine/open_data.py` の `SHELTER_CITATION`）。避難の情報としては見せない。

`manual/area_codes.csv` は総務省「市外局番の一覧」から 1都3県を含む行を写したもので、上の出典の書き方に従う。

## 任意POI索引の取込

全国POIのダウンロードやクラウド件数照会は実行しない。データ本体もコミットしない。Overture Placesは全国規模のGeoParquetで、取得/地域別抽出は[公式getting-dataガイド](https://docs.overturemaps.org/getting-data/)に従い、実行前に対象release・取得量・空き容量を確認する。次のアダプタは、利用者が別途準備したローカルGeoParquetをPyArrowのbatch iteratorで処理し、GeoJSONL中間ファイルを作らず既存SQLite索引へ書く。ファイルには `theme` と `type` の列を残し、値がそれぞれ `places` / `place` の行だけを対象にする。したがって住所テーマの点は取り込まれない。ジオメトリはWKB Pointに限定し、住所の国コードはJPのみ受け付ける。JP以外または複数国が含まれるレコードは拒否する。国コード欠落を許可する `--allow-country-missing` は、すべての行に日本の保守的境界（経度122〜154度、緯度20〜46度、境界を含む）を適用し、範囲外を拒否する。[公式Place schema](https://docs.overturemaps.org/schema/reference/places/place/)の `addresses[].locality` から、日本語の市区町村接尾辞で明示された一意の値だけを粗い `area_label` として保存する（Address schema上の `locality` は市町村または近隣地区を含み得るため、該当形式でない・複数値が競合する場合はnull）。`freeform`・番地・郵便番号等は保存しない。明示的な私有住居カテゴリ（`home`, `house`, `private_house`, `private_residence`, `residence`, `residential_building`, `residential`, `apartment`, `apartments`, `dwelling`）も除外する。

```powershell
uv run --project data-prep python -m tkb_data_prep.import_places `
  --input C:\data\places-japan.geojsonl `
  --output data\processed\places.sqlite3 `
  --provider "Overture Maps" --dataset "places" --version "取得したrelease ID" `
  --source-license-map C:\data\verified-source-licenses.json
```

既に公式配布から適切な範囲を抽出したGeoParquetを使う場合は、同じimporterに `--input-format geoparquet` を指定する。全量取得/展開を意味するコマンドではなく、入力ファイルの作成・download手順は別途見積もる。

```powershell
uv run --project data-prep python -m tkb_data_prep.import_places `
  --input C:\data\places-japan.parquet --input-format geoparquet `
  --output data\processed\national\places.sqlite3 `
  --provider "Overture Maps" --dataset "places" --version "取得したrelease ID" `
  --source-license-map C:\data\verified-source-licenses.json
```

`--source-license-map` は、元条件を人が確認した後で `sources[].dataset` ごとにSPDX IDを与えるJSON object。レコード自身の `sources[].license` を優先し、nullのままで確認済みmappingがないレコードは索引DBには provenance とともに保存するが、検索可能なaliasは作らない。住所国はJPのみ許可し、複数国または非JPの住所がある行を除外する。住所国が欠落する入力は、地理的に日本へ切り出したことを確認して `--allow-country-missing` を指定しても、経度122〜154度・緯度20〜46度の境界内にある点だけを取り込む。変換はSQLiteにバッチで書き込み、既存DBを上書きしない。各名前検索は最大50候補に制限し、上限超過は曖昧として表示する。

取込POIの名称完全一致は未確認候補に過ぎず、Overtureが記載する重複・junk・属性欠落などの品質課題もある。名称だけで所在地を検証済みと表示しない。POI indexはテキスト/座標で、全国の参照画像DBとは別物。参照画像照合を追加する場合は候補周辺の許諾画像だけを個別取得し、別途sourceとライセンスを記録する。

- 文京区オープンデータ「ごみと資源の収集日」（https://www.city.bunkyo.lg.jp/documents/6059/syusyubi.csv）を加工して作成

`manual/knowledge.json` は推理ルールが引く手作りの知識表（自治体の指定ゴミ袋、ゴミの収集地区、大学の時間割）。公開データの加工ではなく、行ごとの `source` に出典か「要確認」「架空（デモ用）」を書く。デモ用の架空の行を実データとして画面や発表に出さない。
文京区の収集地区（`collection_areas` の `city` が文京区の行）だけは手で書かず、上の文京区のオープンデータから `uv run python -m tkb_data_prep.bunkyo_collection` で作る（`fetch.sh` が CSV を `raw/bunkyo/` に取得する）。この変換は文京区の行だけを入れ替え、八王子市などほかの行は変えない。
