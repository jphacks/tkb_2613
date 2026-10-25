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
| 市外局番の一覧（令和8年3月1日現在、Word 版） | 総務省 | https://www.soumu.go.jp/main_content/001072458.doc | [総務省ホームページの利用条件](https://www.soumu.go.jp/menu_kyotsuu/policy/tyosaku.html)（公共データ利用規約 第1.0版に準拠） | 2026-10-23 |

## 出典の書き方

- 郵便番号データ：日本郵便株式会社「郵便番号データ」
- 出典：総務省統計局「市区町村別メッシュ・コード一覧」（https://www.stat.go.jp/data/mesh/m_itiran.html）を加工して作成
- 「国土数値情報（鉄道データ）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2024.html）を加工して作成
- 出典：政府統計の総合窓口（e-Stat）（https://www.e-stat.go.jp/）、総務省統計局「令和2年国勢調査 地域メッシュ統計」を加工して作成
- 出典：文部科学省「学校コード」（https://www.mext.go.jp/b_menu/toukei/mext_01087.html）を加工して作成
- 出典：総務省「市外局番の一覧」（https://www.soumu.go.jp/main_content/001072458.doc）を加工して作成

`manual/area_codes.csv` は総務省「市外局番の一覧」から 1都3県を含む行を写したもので、上の出典の書き方に従う。

`manual/knowledge.json` は推理ルールが引く手作りの知識表（自治体の指定ゴミ袋、ゴミの収集地区、大学の時間割）。公開データの加工ではなく、行ごとの `source` に出典か「要確認」「架空（デモ用）」を書く。デモ用の架空の行を実データとして画面や発表に出さない。
