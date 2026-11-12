# 出典と利用条件

data-prep で使う公開データ。データ本体はリポジトリに含めない（`manual/area_codes.csv` を除く）。
作品の画面や発表資料でこれらのデータを使うときは、下の「出典の書き方」で出典を示す。

| データ | 提供元 | 取得元 | 利用条件 | 取得日 |
|---|---|---|---|---|
| 郵便番号データ（住所の郵便番号、1レコード1行、UTF-8形式） | 日本郵便株式会社 | https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip | 「郵便番号データに限っては日本郵便株式会社は著作権を主張しません。自由に配布していただいて結構です。」（[説明書](https://www.post.japanpost.jp/zipcode/dl/readme.html)） | 2026-10-23 |
| 市区町村別メッシュ・コード一覧（11〜14） | 総務省統計局 | https://www.stat.go.jp/data/mesh/csv/11.csv（12, 13, 14 も） | [統計局ホームページの利用ルール](https://www.stat.go.jp/info/riyou.html)（公共データ利用規約 第1.0版に準拠、CC BY 4.0 と互換） | 2026-10-23 |
| 国土数値情報 鉄道データ（N02、2024年度） | 国土交通省 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2024.html | オープンデータ（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)） | 2026-10-23 |
| 令和2年国勢調査 地域メッシュ統計 4次メッシュ（500m）「人口及び世帯」 | 総務省統計局（政府統計の総合窓口 e-Stat） | https://www.e-stat.go.jp/gis （統計GIS のデータダウンロード。ブラウザで取得） | [e-Stat の利用規約](https://www.e-stat.go.jp/terms-of-use)（政府標準利用規約 第2.0版に準拠、CC BY 4.0 と互換） | 2026-10-23 |
| 学校コード（令和8年5月1日時点・暫定版、CSV） | 文部科学省 | https://www.mext.go.jp/b_menu/toukei/mext_01087.html | [文部科学省ホームページの利用ルール](https://www.mext.go.jp/b_menu/1351168.htm)（公共データ利用規約 第1.0版に準拠、CC BY 4.0 と互換） | 2026-10-25 |
| 国土数値情報 バス停留所データ（P11、令和4年度版。平成22年度版は使わない） | 国土交通省 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P11-v3_0.html （`P11-22_{11..14}_SHP.zip`） | 「国土数値情報ダウンロードサイトコンテンツ利用規約」に基づく（オープンデータ）。平成22年度版は非商用なので取り込まない | 2026-11-12 |
| 国土数値情報 行政区域データ（N03、2026年1月1日時点） | 国土交通省 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html （`N03-20260101_{11..14}_GML.zip`） | オープンデータ（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)） | 2026-11-12 |
| 指定緊急避難場所・指定避難所データ（都道府県別 CSV、11000〜14000 の `_1`・`_2`） | 国土地理院 | https://hinanmap.gsi.go.jp/hinanjocp/defaultFtpData/csv/13000_2.csv など（案内は https://www.gsi.go.jp/bousaichiri/hinanbasho.html ） | [国土地理院コンテンツ利用規約](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html)（公共データ利用規約 第1.0版。CC BY 4.0 と互換）と、ダウンロードサイトの「ご利用上の注意」（最新でない場合や未掲載の場合があること、第三者に提供するときはこの注意が伝わるようにすること） | 2026-11-12 |
| 法人番号公表サイト 基本3情報 全件データ（CSV 形式・Shift-JIS、埼玉・千葉・東京・神奈川） | 国税庁 | https://www.houjin-bangou.nta.go.jp/download/zenken/ （ブラウザで取得して `raw/houjin/` に置く） | [法人番号公表サイトの利用規約](https://www.houjin-bangou.nta.go.jp/riyokiyaku/index.html)（公共データ利用規約 第1.0版に準拠。CC BY 4.0 と互換） | 2026-11-12（2026-10-30 版） |
| 市外局番の一覧（令和8年3月1日現在、Word 版） | 総務省 | https://www.soumu.go.jp/main_content/001072458.doc | [総務省ホームページの利用条件](https://www.soumu.go.jp/menu_kyotsuu/policy/tyosaku.html)（公共データ利用規約 第1.0版に準拠） | 2026-10-23 |

## 出典の書き方

- 郵便番号データ：日本郵便株式会社「郵便番号データ」
- 出典：総務省統計局「市区町村別メッシュ・コード一覧」（https://www.stat.go.jp/data/mesh/m_itiran.html）を加工して作成
- 「国土数値情報（鉄道データ）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2024.html）を加工して作成
- 出典：政府統計の総合窓口（e-Stat）（https://www.e-stat.go.jp/）、総務省統計局「令和2年国勢調査 地域メッシュ統計」を加工して作成
- 出典：文部科学省「学校コード」（https://www.mext.go.jp/b_menu/toukei/mext_01087.html）を加工して作成
- 出典：総務省「市外局番の一覧」（https://www.soumu.go.jp/main_content/001072458.doc）を加工して作成
- 「国土数値情報（バス停留所データ）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P11-v3_0.html）を加工して作成。令和4年度（作成時点は概ね2022年8月）のデータ
- 「国土数値情報（行政区域データ）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html）を加工して作成
- 出典：国税庁法人番号公表サイト（国税庁）（https://www.houjin-bangou.nta.go.jp/download/zenken/）を加工して作成
- 「指定緊急避難場所データ」「指定避難所データ」（国土地理院）（https://www.gsi.go.jp/bousaichiri/hinanbasho.html）をもとに作成。最新でない場合や未掲載の場合があります（最新の状況は各市町村にご確認ください）

画面で避難所の表を根拠に出すときは、上の注記（最新でない場合や未掲載の場合があること）を必ず添える（`engine/src/tkb_engine/open_data.py` の `SHELTER_CITATION`）。避難の情報としては見せない。

`manual/area_codes.csv` は総務省「市外局番の一覧」から 1都3県を含む行を写したもので、上の出典の書き方に従う。

`manual/knowledge.json` は推理ルールが引く手作りの知識表（自治体の指定ゴミ袋、ゴミの収集地区、大学の時間割）。公開データの加工ではなく、行ごとの `source` に出典か「要確認」「架空（デモ用）」を書く。デモ用の架空の行を実データとして画面や発表に出さない。
