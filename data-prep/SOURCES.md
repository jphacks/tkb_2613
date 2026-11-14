# 出典と利用条件

data-prep で使う公開データ。データ本体はリポジトリに含めない（`manual/area_codes.csv` を除く）。
作品の画面や発表資料でこれらのデータを使うときは、下の「出典の書き方」で出典を示す。

| データ | 提供元 | 取得元 | 利用条件 | 取得日 |
|---|---|---|---|---|
| 郵便番号データ（住所の郵便番号、1レコード1行、UTF-8形式） | 日本郵便株式会社 | https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip | 「郵便番号データに限っては日本郵便株式会社は著作権を主張しません。自由に配布していただいて結構です。」（[説明書](https://www.post.japanpost.jp/zipcode/dl/readme.html)） | 2026-10-23 |
| 市区町村別メッシュ・コード一覧（全国01〜47。関東向け既存処理は11〜14） | 総務省統計局 | https://www.stat.go.jp/data/mesh/csv/01.csv〜47.csv（都道府県別） | [統計局ホームページの利用ルール](https://www.stat.go.jp/info/riyou.html)（公共データ利用規約 第1.0版に準拠、CC BY 4.0 と互換） | 出典確認 2026-11-14。全国版を取得・生成済み（加工済みParquetはローカルignored出力） |
| 国土数値情報 鉄道データ（N02、2024年度） | 国土交通省 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2024.html | オープンデータ（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)） | 2026-10-23 |
| 国土数値情報 市町村役場等及び公的集会施設データ（P05、第3.0版、2022年4月基準） | 国土交通省 | 詳細 https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05-v3_0.html / ZIP https://nlftp.mlit.go.jp/ksj/gml/data/P05/P05-22/P05-22_GML.zip （7.98MB） | 個別ページの「適用する利用規約に基づく（オープンデータ）」に従い、現行サイト規約のPDL1.0で利用。出典と加工表示を記録 | 2026-11-14取得・生成。79,532件を検査、国内mesh gate通過79,529件・47/47県、SQLite 102,424,576 bytes（全てignored） |
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
- 「国土数値情報（市町村役場等及び公的集会施設データ、第3.0版）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05-v3_0.html）、PDL1.0（https://www.digital.go.jp/resources/open_data/public_data_license_v1.0）をもとに作成。所在地属性（P05_004）は破棄し、名称・施設分類・位置・行政区域コードのみ索引化
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

全国の公的施設候補には国土数値情報P05の2022年版を利用できる。公式ZIPの取得先は `https://nlftp.mlit.go.jp/ksj/gml/data/P05/P05-22/P05-22_GML.zip`。ZIPは外側に都道府県別ZIPを47個含み、各ZIPにはGeoJSON FeatureCollection・Shapefile・メタデータが入る（`_GML.zip` という名称でも、配布ZIP内にGML本文はなくGeoJSONを使う）。2026-11-14の検査で79,532件を確認し、分類コードは1:1,908、2:4,272、3:2,562、4:21,302、5:49,488だった。国内bbox/1km mesh gateで79,529件（47/47県）を索引化し、3件はmesh所属を確認できず除外した。SQLiteは102,424,576 bytes、`area_label` は79,529件すべてに付与できた。primary nameは67,948種類、うち同一名称を持つ複数レコードが15,093件ある。名前検索キーは92,960種類で、そのうち4,546キーが複数POIへ対応し、該当する15,204 POIは曖昧候補として扱う。変換は都道府県を一つずつ読み、47県の存在と属性コードを事前検証してから索引を作成する。入力上限は16 MiB、各都道府県ZIP/entry/GeoJSON上限は16 MiB、全entry展開合計128 MiB、個別Featureは1 MiB。ZIPを展開せずに処理し、絶対/親相対パスを拒否する。

```powershell
uv run --project data-prep python -m tkb_data_prep.import_ksj_p05 `
  --input data\raw\P05-22_GML.zip `
  --output data\processed\national\places.sqlite3 `
  --mesh-index data\processed\national\muni_mesh.parquet
```

生成する索引は新規作成のみで、同じ出力がある場合は上書きしない。POI索引schema v3、名称・位置・施設分類コード・自治体コード・source provenanceを保存する。完全所在地は取り込まない。`area_label` はP05行政区域コードを全国mesh Parquet内の自治体コード・自治体名に一意対応できる場合だけ付与し、対応しない場合はnull。日本国内bboxと1km mesh所属ゲートを適用する。出典・加工表示とPDL1.0、元データURL、版年を各sourceへ保存する。P05公式ページは、すべての施設情報を取得できていない可能性に注意を促している。

全国POIのダウンロードやクラウド件数照会は実行しない。データ本体もコミットしない。Overture Placesは全国規模のGeoParquetで、取得/地域別抽出は[公式getting-dataガイド](https://docs.overturemaps.org/getting-data/)に従い、実行前に対象release・取得量・空き容量を確認する。次のアダプタは、利用者が別途準備したローカルGeoParquetをPyArrowのbatch iteratorで処理し、GeoJSONL中間ファイルを作らず既存SQLite索引へ書く。ファイルには `theme` と `type` の列を残し、値がそれぞれ `places` / `place` の行だけを対象にする。したがって住所テーマの点は取り込まれない。ジオメトリはWKB Pointに限定し、住所の国コードはJPのみ受け付ける。JP以外または複数国が含まれるレコードは拒否する。国コード欠落を許可する `--allow-country-missing` は、すべての行に日本の保守的境界（経度122〜154度、緯度20〜46度、境界を含む）を適用し、範囲外を拒否する。さらに必須の `muni_mesh.parquet` を一度ロードし、既存の `jismesh` 変換で得る1km三次mesh codeが全国の市区町村mesh一覧に含まれることを要求する。既定pathは `data/processed/national/muni_mesh.parquet` で、存在しない場合はfail closed。出力を使う前に `make data-national-gazetteer` で作成するか `--mesh-index` で別の全国mesh表を指定する。この判定は行政区域ポリゴンとの正確な点内判定ではなく1km cell membershipであり、海岸沿いでは自治体と海が同じcellに入る場合がある。つまりbboxとmesh gateは遠方の国外点を除外する保守的な候補filterで、海岸線境界を証明しない。[公式Place schema](https://docs.overturemaps.org/schema/reference/places/place/)の `addresses[].locality` から、日本語の市区町村接尾辞で明示された一意の値だけを粗い `area_label` として保存する（Address schema上の `locality` は市町村または近隣地区を含み得るため、該当形式でない・複数値が競合する場合はnull）。`freeform`・番地・郵便番号等は保存しない。明示的な私有住居カテゴリ（`home`, `house`, `private_house`, `private_residence`, `residence`, `residential_building`, `residential`, `apartment`, `apartments`, `dwelling`）も除外する。

```powershell
uv run --project data-prep python -m tkb_data_prep.import_places `
  --input C:\data\places-japan.geojsonl `
  --output data\processed\places.sqlite3 `
  --mesh-index data\processed\national\muni_mesh.parquet `
  --provider "Overture Maps" --dataset "places" --version "取得したrelease ID" `
  --source-license-map C:\data\verified-source-licenses.json
```

既に公式配布から適切な範囲を抽出したGeoParquetを使う場合は、同じimporterに `--input-format geoparquet` を指定する。全量取得/展開を意味するコマンドではなく、入力ファイルの作成・download手順は別途見積もる。

```powershell
uv run --project data-prep python -m tkb_data_prep.import_places `
  --input C:\data\places-japan.parquet --input-format geoparquet `
  --output data\processed\national\places.sqlite3 `
  --mesh-index data\processed\national\muni_mesh.parquet `
  --provider "Overture Maps" --dataset "places" --version "取得したrelease ID" `
  --source-license-map C:\data\verified-source-licenses.json
```

`--source-license-map` は、元条件を人が確認した後で `sources[].dataset` ごとにSPDX IDを与えるJSON object。レコード自身の `sources[].license` を優先し、nullのままで確認済みmappingがないレコードは索引DBには provenance とともに保存するが、検索可能なaliasは作らない。住所国はJPのみ許可し、複数国または非JPの住所がある行を除外する。住所国が欠落する入力は、地理的に日本へ切り出したことを確認して `--allow-country-missing` を指定しても、経度122〜154度・緯度20〜46度の境界内かつ全国mesh表の1km codeに所属する点だけを取り込む。POI索引schema versionを3へ上げたため、旧versionの索引は実行時に拒否される。POI本体を再生成するには同じ手順でSQLite索引を新規出力する（既存出力は上書きしない）。変換はSQLiteにバッチで書き込み、既存DBを上書きしない。各名前検索は最大50候補に制限し、上限超過は曖昧として表示する。

取込POIの名称完全一致は未確認候補に過ぎず、Overtureが記載する重複・junk・属性欠落などの品質課題もある。名称だけで所在地を検証済みと表示しない。POI indexはテキスト/座標で、全国の参照画像DBとは別物。参照画像照合を追加する場合は候補周辺の許諾画像だけを個別取得し、別途sourceとライセンスを記録する。

### Overture Places 関東1都6県の索引（P05と合算）

| 項目 | 内容 |
|---|---|
| 出典 | Overture Maps Foundation, Places（release `2026-10-21.0`）。<https://docs.overturemaps.org/guides/places/> ・ 帰属 <https://docs.overturemaps.org/attribution/> ・ schema <https://docs.overturemaps.org/schema/reference/places/place/> |
| 取得日 | 2026-11-14（release番号は <https://docs.overturemaps.org/getting-data/> と `overturemaps releases list` で確認） |
| license | テーマ全体の単一licenseではなく、行の `sources[].license` にsourceごとに入っている。関東分の実データでは `CDLA-Permissive-2.0`（Meta等）、`Apache-2.0`（Foursquare）、`CC0-1.0`（AllThePlaces）の3種だけで、nullは0件だった。そのため `--source-license-map` は使っていない。licenseがnullの行が将来のreleaseで現れた場合は、既存の挙動どおり検索aliasを作らない |
| 帰属表示 | Foursquare行は「Copyright 2024 Foursquare Labs, Inc. All rights reserved.」と「Foursquare data was transformed to the Overture schema.」（<https://opensource.foursquare.com/places-notice-txt/>）を表示する条件がある。他のsourceは各licenseのURLを記録する。画面に出すときは索引の `sources[].attribution` / `license_id` を使う |
| 範囲 | 関東1都6県（茨城・栃木・群馬・埼玉・千葉・東京・神奈川＝都道府県コード08〜14）。bbox `138.35,34.85,140.95,37.2` で取得後、`muni_mesh.parquet` の1km meshの市区町村コード先頭2桁が08〜14のものだけを残す。県境をまたぐmeshは、関東側の市区町村が1つでも含まれれば残るため、福島・山梨・静岡などの境界の数百件が混ざり得る |
| 件数 | P05 79,529件 + Overture 1,032,210件 = 1,111,739件（ファイル約1.96GB）。bboxで取得した生データは1,132,013行・約213MB |

作り方（管理者向け。ディスクは生データ約0.2GB、中間索引約1.9GB、完成索引約2GBが要る。取込は約12分、合算は約5分）：

```bash
# 1. 取得（overturemaps CLI。リポジトリの依存には入れず一時実行する）
uv tool run --from overturemaps overturemaps download   --bbox=138.35,34.85,140.95,37.2 -f geoparquet -t place -r 2026-10-21.0   -o data/raw/overture/kanto_places_2026-10-21.0.parquet

# 2. 関東分だけの索引にする（CLIの出力には theme/type 列がないので --assume-place-rows が要る）
uv run --project data-prep python -m tkb_data_prep.import_places   --input data/raw/overture/kanto_places_2026-10-21.0.parquet --input-format geoparquet   --assume-place-rows --prefecture-codes 08,09,10,11,12,13,14   --output data/processed/kanto/overture_kanto.sqlite3   --mesh-index data/processed/national/muni_mesh.parquet   --provider "Overture Maps" --dataset overture-places --version 2026-10-21.0   --attribution "Overture Maps Foundation, Places 2026-10-21.0 (https://docs.overturemaps.org/attribution/)"

# 3. P05の索引と合算（入力は読むだけ。出力が既にあれば止まる）
uv run --project data-prep python -m tkb_data_prep.merge_places   --input data/processed/national/places.sqlite3 data/processed/kanto/overture_kanto.sqlite3   --output data/processed/kanto/places.sqlite3
```

`--prefecture-codes` は `--mesh-index` の `muni_code` を使う。`--assume-place-rows` は `overturemaps download -t place` の出力（行がすべてPlacesの `place`）にだけ使い、`theme` / `type` 列がある入力ではその値も確認する。私有住居カテゴリの除外は従来どおり効く。Overtureは名称の表記ゆれ・重複・閉店済みを含むので、名称が一致しても未確認候補として扱う。

- 文京区オープンデータ「ごみと資源の収集日」（https://www.city.bunkyo.lg.jp/documents/6059/syusyubi.csv）を加工して作成

`manual/knowledge.json` は推理ルールが引く手作りの知識表（自治体の指定ゴミ袋、ゴミの収集地区、大学の時間割）。公開データの加工ではなく、行ごとの `source` に出典か「要確認」「架空（デモ用）」を書く。デモ用の架空の行を実データとして画面や発表に出さない。
文京区の収集地区（`collection_areas` の `city` が文京区の行）だけは手で書かず、上の文京区のオープンデータから `uv run python -m tkb_data_prep.bunkyo_collection` で作る（`fetch.sh` が CSV を `raw/bunkyo/` に取得する）。この変換は文京区の行だけを入れ替え、八王子市などほかの行は変えない。
