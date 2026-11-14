# 写真から場所を推定する汎用設計（提案）

状態: 第一〜第四実装スライス済み。撮影場所候補の生成、同意付きCommons参照画像の近似複製照合、PhotoPlaceResultを条件付きで使う保守的な投稿横断`residential_area`経路まで実装済み。写真候補だけから居住地や現在地を決めない。別角度/視点照合と撮影地点推定は未実装。

初回スライスでは投稿画像ごとの `PhotoPlaceResult` を共通型と `conclusions` SSE/診断snapshotに追加した。駅候補は重なる高確度OCR/VLM、施設候補は許諾済みローカルSQLite POI索引を使う。写真場所結果はプロフィール属性と別型のままだが、本人が写真投稿で「自宅近くの<X>」と明示し、許諾済み一意POIの粗い行政地域が分かり、別投稿にも同地域の近隣・日常・帰宅・通勤等の独立文脈と `PLACE_TEXT` 根拠がある場合だけ、居住地域の弱い候補を作る。結果単独では候補を作らない。

## 1. 目的と境界

写真内の観測（看板文字、駅名標、建物・地形の特徴など）と、利用条件を確認した地理データを照合し、必要な場合だけ候補地を絞る。狙いは `post_id` と画像番号に結び付いた「撮影場所候補」である。候補が一意に絞れない、証拠が古い/弱い、データがない、または情報が競合する場合は `unknown` を返す。

この候補を `ProfileAttribute.RESIDENTIAL_AREA` や `realtime_location` に直接変換しない。写真が撮影された場所は、旅行・通勤・訪問先・転載画像でもあり得る。居住エリアは、本文にある明示的な「家の近く」等の本人との関係文脈と、別投稿を含む独立した証拠経路が成立した場合に限り、別の推論規則で扱う。投稿の引用・内覧・見学・訪問・第三者・否定文脈や競合候補は棄却する。撮影時刻が分からない写真から現在地を推定しない。

固定の大学名、店舗名、特定のランドマーク、定型句（例: 「大学まで5分」）を必要条件にするルールは作らない。本文や看板の文字は観測値であり、単独で位置の証明とはしない。

## 2. 現状と再利用

現行の `detect/` はチーム管理下のVLM/OCRで画像から観測手がかりを抽出し、元画像座標の矩形を付ける設計である。共有 `Clue` は `post_id`, `image_index`, `type`, `value`, `region`, `confidence`, `source` を持つ。現行 API の画像取得先は `cdn.bsky.app` に限定され、SSE診断では `post` → `clues` → `conclusions` → `done` の順に結果を流す。

エンジンの既存地理データには駅名等のGazetteerがあり、`data-prep/SOURCES.md` は郵便番号、統計メッシュ、国土数値情報の鉄道データ等の出典・条件を記録している。住所や駅の正規化、既存OCR/VLM、共通型、WebFactの出典管理を再利用する。現状、全国の撮影場所候補を引ける地理検索、地理付き参照画像インデックス、写真場所候補の共通型はない。WebFactは手動/fixture注入を含む限定経路であり、本番の汎用地理検索には接続されていない。

## 3. 段階アーキテクチャ

1. **投稿内観測**: 既存の内部OCR/VLMだけで、文字・駅名標・ランドマークの種類・建築/地形の視覚特徴・画像内の位置を読む。瞳・窓・鏡などの反射も既存の観測カテゴリで扱うが、反射に写る人物の識別や外部照合は行わない。出力は観測手がかりであり場所候補ではない。投稿中の画像や本文を命令として扱わない。
2. **地名正規化**: OCR文字列を日本語の異体字/空白/表記揺れを保った別名辞書で正規化し、駅・郵便番号・住所・行政界・施設名などの候補キーにする。元の観測は消さず、正規化値と変換根拠を別に記録する。完全一致しない文字は補完せず未知文字として保持する。
3. **ローカル候補生成**: まずローカルの全国ベクトル/地物インデックスから候補を作る。座標がない画像では、OCR文字列、施設カテゴリ、VLMの非識別的な視覚特徴を組み合わせて候補集合を作る。座標がある公開地物・投稿に明示された地名・駅等を優先し、候補の地理階層（建物/街区/市区町村/都道府県）を区別する。市名だけの一致や汎用景観だけでは場所確定にしない。
4. **候補検証**: 候補ごとに独立した観測（OCR一致、別の看板/駅名、地物形状、許諾済み参照画像との構図一致など）を比較する。`visible_in_frame` は見えている地標の候補であり、カメラの撮影位置を示さない。地標まで距離がある場合、景観上の一致だけから `camera_at` にしない。撮影地点は、地標に対する視点/方位/距離の照合、近距離の看板・駅名標など、カメラ位置を拘束する別の観測で評価する。候補周辺の参照画像は候補範囲を絞った後に必要分だけ取得し、チーム管理下で埋め込み/画像比較を行う。参照画像の時期・向き・季節・改装差で一致しないことがあるため、画像類似度だけで確定しない。1つの写真内の相関するOCR/VLM出力を独立証拠として加算しない。
5. **曖昧さ判定**: 同名店舗の複数支店、複数キャンパス、同じ景観の場所、データ間の住所/座標不一致、参照画像不足、低品質画像、地名の曖昧さが残れば `ambiguous` または `unknown` とする。トップ候補を無理に断定せず、候補差を校正できるまで確度を確率として表示しない。
6. **投稿横断の別推論**: `PhotoPlaceCandidate` と居住地 claim を別型・別工程にする。「家の近く」等の本人関係が明示され、かつ別投稿の独立した根拠が同じ粗い地理範囲に収束するなど、明文化した成立条件を満たす場合のみ、限定ルールが弱い `residential_area` 候補を生成する。写真場所候補単独はこのルールの必須条件を満たさない。再診断・仮除外では候補に至る証拠経路を再計算する。
7. **任意の外部補完**: ローカル候補が不足する場合に加え、候補が複数に割れる場合や住所/視覚根拠が不足する場合に、検証目的で外部検索を使える設計とする。ただし診断ごとの明示同意と送信内容の適合が前提。検索語は識別的な施設名・駅名・地標など、投稿から読めた公開名称と必要最小限の粗い地理文脈に限定する。一般的な景色語の羅列や、人物/私的投稿を識別できる検索語は使わない。画像、画像crop、画像埋め込み、顔/瞳/反射、本文全文、DID、投稿URI、ハンドル、氏名、未加工OCR全文は送らない。Brave Image Searchはテキスト `q` を受け取る画像検索であり、逆画像検索ではない。画像をBrave等の検索APIへ渡して類似画像を探す設計にしない。外部結果は候補生成/検証に使い、公式/公的な根拠へたどれない限り検証済み事実としない。

外部検索同意はログインやプロフィール検索の同意から推定しない。プロフィールWeb同意と写真場所Web同意は別boolで診断ごとに受け取り、開始直後にUI状態をfalseへ戻す。写真場所検索を有効にできるのは非モック実行、`BRAVE_SEARCH_API_KEY` があり、かつ `DIAGNOSE_DAILY_LIMIT > 0` の場合のみ。`DIAGNOSE_DAILY_LIMIT=0` は診断を無制限にするため、Braveキーと診断同意があっても写真場所検索を無効にし、外部通信なしで検索不可として表示する。この追加ガードは既存プロフィール検索の挙動に影響しない。対象画像がローカル `unknown` / `ambiguous` で、画像内矩形を持つ高確度OCR/VLMの `shop` / `landmark` / `station_sign` Clueが安全検査を通った場合のみ対象とし、同一検索語を重複排除して診断全体で最大3クエリ、最大5件/応答とする。実際の送信はBrave Place SearchのGET `/res/v1/local/place_search` に `q=<施設名または駅名>`, `country=JP`, `count=5`, `search_lang=ja`, `ui_lang=ja-JP` を付け、tokenはサーバー側headerだけに載せる。汎用検索語は送らず、地域文脈も現行実装では送らない。

許可例は架空の「○○駅」「△△美術館」。診断前は画像を解析していないので、実際の検索語はUIに事前表示できず、同意文で例を示す。検索語をアプリのログ/DB/キャッシュへ保存しない。Braveの検索語は最大90日保持され、Braveの有料プランと支払情報が必要となるため、その条件を同意文に明示する。`DIAGNOSE_DAILY_LIMIT=3` の本番例と最大3クエリ/診断により、アカウントあたり最大9検索/日となる。無制限設定（0）は本番費用上限を外すため使用しない。

送信禁止: 人名、`org_text` / `place_text`、本文/プロフィール文、住所・郵便番号・電話番号、数字または不明文字 `x` を含む文字列、URL/メール/電話、文や長文、DID、投稿URI、ハンドル、画像URL、画像画素/crop/embedding、顔/瞳/反射。Brave Image Searchは文字による画像検索で逆画像検索ではないため画像自体を送らない。Braveの `country=JP` は検索スコープにすぎないため、採用結果は `postal_address.country == "JP"` を必須にする。`title` は送信名とNFKC英数字/かな等を比較する厳格な完全一致のみ採用し、URLは公開HTTPSを検査する。Brave一時 `id` は約8時間で失効するため読まずに破棄し、snippet/thumbnail/full addressも使わない。結果は未確認の `visible_in_frame` 候補としてのみ表示する。施設の所在地・写真の撮影地点を確定せず、公式/公的な独立根拠が後続で確認されるまで検証済み事実にしない。

## 4. 現行共有型/API

現行契約はPythonの `common/` と画面の `web/src/types/` で対にしている。以下は実データ形の例で、未使用フィールドは既定値/省略可として扱う。

```json
{
  "post_id": "at://…",
  "image_index": 0,
  "status": "candidate",
  "granularity": "facility",
  "candidates": [{
    "place_id": "source:stable-id",
    "label": "正規化した候補名",
    "place_type": "facility",
    "photo_relation": "visible_in_frame",
    "area_label": null,
    "score": null,
    "evidence": [{"kind": "clue", "clue_index": 3}, {"kind": "reference", "reference_id": "ref:…"}],
    "source_ids": ["geo:…"]
  }],
  "reason_codes": [],
  "lookup_status": "local_only"
}
```

- `PhotoPlaceResult` は `post_id`, `image_index`, `status`, `granularity`, `candidates`, `reason_codes`, `lookup_status` を持つ。`status` は `candidate | ambiguous | unknown | unavailable`、`lookup_status` は `local_only | web_searched | reference_checked | unavailable`。`reason_codes` はその状態と矛盾しない理由だけを含める。不明なら候補を空配列にする。
- 候補要素は安定した出典ID、表示ラベル、地物種別（`station | landmark | facility | address | area | unknown`）、地理粒度、`photo_relation`、証拠参照、出典IDを持つ。`photo_relation` は候補ごとの `visible_in_frame | camera_nearby | camera_at` のいずれかで、画像ごとの結果全体には置かない。地標が写っているだけなら `visible_in_frame` とし、距離のある地標から `camera_at` を導かない。 `camera_nearby` / `camera_at` は視点照合や近距離看板等で撮影地点を拘束できた場合に限る。座標を返す必要がある場合は粗く丸めた座標を別途定義し、民家/個人施設の正確な座標は出さない。`score` は未校正なら `null`。座標や参照画像メタデータは内部計算用と画面表示用を分ける。
- `PhotoPlaceEvidence` は観測clue indexまたは参照画像IDを指す。`PhotoPlaceSource` は出典・ライセンスと任意の `source_url` を持つ。Brave結果は一時IDを持続IDとして使わず、source URLを公開HTTPS検査したうえで表示する。
- `PhotoPlaceResult` は `ProfileAttribute` ではなく、直接 `RESIDENTIAL_AREA` / `REALTIME_LOCATION` / `WebFact` へ変換しない。保守的な居住地域経路では、元画像の `Clue` evidence（post/clue indexから画像を特定）、同じ投稿の候補名に係る明示的な家周辺文脈、別投稿の独立した同地域根拠をAND経路に含める。全根拠を必須にするため、どちらの投稿を除外しても経路が落ちる。専用のPhotoPlaceResult ProfileEvidence型は追加せず、Clueと投稿文の既存参照から候補を再構成できる。

## 5. API / SSE 契約との同期

実装では診断結論に `photo_place_results: PhotoPlaceResult[]` を追加し、既存順序 `post` → `clues` → `conclusions` → `done` の `conclusions` 内でまとめて渡す。`photo_place_lookup_status` は各結果の `lookup_status` に含める。新しいSSEイベントは増やさない。後に候補の逐次表示が必要になった場合だけ、独立イベントを追加し、イベント順・部分結果・重複/欠落・途中切断を契約に書く。

API/SSE契約、同意状態、エラー/未実行状態は `docs/api-sse-contract.md` に同期済み。Braveへ施設/駅名を送る変更に合わせ `AGENTS.md` と `CLAUDE.md` も更新し、同意UIでカテゴリ・例・提供先・保持期間・費用条件と、診断前は実際の名称を確認できないことを説明している。

## 6. 候補データとライセンス管理

POI索引は名称/住所/座標で候補を作る。視覚照合は候補周辺で権利確認済みの参照画像に限定し、両者を同じデータベース/ライセンスとみなさない。全国の参照画像を事前に全件ダウンロード・保持する前提にはしない。まず軽量な地名・地物インデックスで地域を絞り、利用条件を確認できた参照画像だけオンデマンドで取得する。検索APIの利用条件、保存/キャッシュ期限、再配布条件は導入前に確認する。

| データ候補 | 用途 | 条件・注意 |
| --- | --- | --- |
| 既存 `data-prep` データ（郵便番号、駅/鉄道、統計メッシュ） | OCR正規化、駅名/行政範囲の粗い候補生成 | 出典・条件を `data-prep/SOURCES.md` に追記。既存の駅・住所データだけで全施設や撮影位置を特定できるとは扱わない。 |
| 国土数値情報・国土地理院等の地物/行政界 | 全国の地理索引、地物タイプ・行政階層の照合 | データセット/レイヤー単位で利用規約と更新日を確認。地図タイルの規約をベクターデータや航空写真へ一律に適用しない。 |
| Overture Maps Places | 名称/住所/座標/カテゴリを持つ全国POI候補索引。地理範囲で部分取得し、写真のOCR名称等を照合する | [公式Placesガイド](https://docs.overturemaps.org/guides/places/)でデータ構造・配布単位・ライセンスと更新日を確認し、取得時のメタデータを記録する。地域別カバレッジは未検証であり、網羅性を前提にしない。これはテキスト/座標のPOI索引で、参照画像DBではない。 |
| OpenStreetMapデータ | 道路・POI等のローカル候補索引 | ODbLの帰属表示と派生データベースの共有条件を確認し、他ライセンスのデータと混同しない。公開タイルを大量取得しない。 |
Mapillaryの地理付き街路画像 | 候補を絞った地域の視点画像との内部比較 | Mapillaryの説明では街路画像とAPI/GIS連携を提供し、画像はCC BY-SAで帰属表示が必要。取得画像/特徴量の保存・変換・表示がライセンスとAPI条件に沿うか確認し、画像ごとのURL、作者、ライセンス、取得日を保持する。地域全体を先に保存しない。 |
| Wikimedia Commonsの位置付き画像 | 地名/座標周辺のランドマーク画像を候補検証 | GeoDataで座標周辺検索できる。ファイルごとにライセンス・作者・帰属条件が異なるため、ファイルページごとに確認し、条件不明/非互換は使わない。初期実装は`CC0 1.0` / `CC BY 3.0` / `CC BY 4.0`に限定し、SA/GFDL等は使わない。画像と比較特徴は診断内メモリのみ。 |

ライセンス記録は最低限 `provider`, `asset_id`, `canonical_url`, `creator`, `license_id/version`, `dataset_version/update_date`, `attribution_text`, `retrieved_at`, `allowed_operations`, `cache_expiry`, `terms_checked_at` を含める。画像本体と派生特徴量の保持が許されるか個別に判断する。出典を追跡できない参照画像・検索結果画像は比較対象にしない。

## 7. プライバシーと安全策

- 投稿写真/本文は既存方針どおりメモリ内で扱い、ログ・ディスク・共有キャッシュに保存しない。元画像ピクセルはチーム管理のVLM/OCRや内部比較器にのみ渡す。第三者AI/検索APIへ送らない。
- 外部地理/画像カタログの取得は公開情報でも診断対象の私的投稿を送らない。外部検索は明示同意後の最小テキストのみ。クエリ全文・画像URL・DID/URIをログしない。
- 顔認識、人物照合、瞳/反射の人物特定、家屋や個人の正確な座標特定は対象外。個人宅が候補に含まれる場合は地番/座標を表示せず、地点候補から除外する。
- 出力に必須証拠を付け、投稿内引用や画像中のプロンプトを命令として実行しない。Web結果は untrusted な観測として扱い、検索結果のsnippetだけで確定しない。
- 表示は「写真の撮影場所候補」とし、本人の居住地/現在地を意味しないことを明記する。信頼度が未校正なら順位・スコアを確率として見せない。
- ユーザーが明示同意を取り消すか診断を終了したら、診断内候補・検索応答・一時画像を破棄する。再利用キャッシュは公開参照データの利用条件が許す場合だけ別管理する。

## 8. 評価計画と受け入れ基準

評価セットは許諾・出典が明確な公開地点画像、チームが撮影し利用許諾を得た公共地点の写真、合成/加工画像を中心にし、個人宅、メンバー宅周辺、無断の顔写真を使わない。既知正解地点は評価用に分離し、モデル/検索索引へ漏らさない。日本の地域差、漢字/ひらがな/ローマ字表記、都市/郊外/地方、季節・時間帯を含める。

| ケース | 期待 |
| --- | --- |
| 一意な駅名標 + 整合する地理索引 | 駅候補を根拠付きで出し、撮影場所候補としてのみ返す |
| ありふれた駅/建物/道路景観 | `ambiguous` または `unknown` |
| 同名店舗・支店、複数キャンパス、同じ地名の施設 | 競合を検出し、単一地点へ断定しない |
| OCR誤読/部分文字/別出典との座標衝突 | 候補を出さないか `unknown`、誤りを確定扱いしない |
| 古い参照画像、改装/建替え、季節・角度違い | 過剰一致を避け、必要なら不明にする |
| 引用・訪問・旅行・内覧の投稿に「家の近く」がない | 居住地候補に結び付けない |
| 「家の近く」記述のみ、または同一画像の重複観測のみ | 居住地候補にしない。独立経路を要求 |
| 外部同意なし | 外部検索呼び出し0回 |
| 外部同意あり | 許可されたテキストのみ送信。画像/顔/投稿本文/DID/URIは送らない |
| 外部同意あり、許可Clueなし/索引候補が一意 | Braveを呼ばず、ローカルunknown/候補のまま。検索不可状態を誤って付けない |
| 外部結果のcountry欠落/非JP、title不一致、非公開HTTPS URL | 候補に採用しない。住所詳細/temporary id/thumbnail/snippetは保存しない |
| 同名ローカル支店とBrave候補 | 独立に残し、住所/座標等の独立一致なしに統合しない |
| 参照画像のライセンス情報欠落/期限・条件違反 | 取得/使用しない |

追加ケース: 許可Clueなし、またはローカル候補が一意な画像ではBraveを呼ばず、ローカルunknown/候補のままにする。country欠落/非JP、title不一致、非公開HTTPS URLの外部結果は採用しない。同名ローカル支店とBrave候補は住所/座標等の独立一致なしに統合しない。

受け入れ基準:

1. 地点評価を `top-1/top-3` だけでなく、地理階層別の誤差、候補被覆率、unknown適合率、曖昧ケースの誤断定率で評価し、閾値は検証データで事前に定める。閾値未達ならunknownに倒す。
2. `visible_in_frame` だけの地標から `camera_nearby` / `camera_at` を推定しない。距離のある地標だけを根拠に撮影地点を断定しない。曖昧・競合ケースの単一地点断定を0件にする。地名/住所を出す主張は、独立した検証可能な出典と観測根拠を追跡可能にする。
3. PhotoPlaceResult単独で `residential_area` / `realtime_location` が生成されないことをテストする。関係推論は独立投稿、明示的な本人関係、引用/訪問除外、削除後再計算を通過する。
4. 画像bytesが外部検索クライアントへ渡らないこと、同意なし検索0回、同意ありでも送信フィールドの許可リスト外が0件であることをテストする。最大3クエリ/診断、titleの完全一致、`postal_address.country == JP`、未確認外部結果の区別もテストする。
5. 外部/ローカル参照画像ごとにライセンス記録があり、許諾外の画像や出典不明画像を候補比較器へ渡さないことをテストする。
6. すべての候補とclaimが `post_id/image_index`・clue index・source IDへたどれ、SSEの参照切れ/不正列挙値を画面が拒否する。
7. 未校正のスコアを確率や「正確さ%」として表示しない。遅延・検索数・地域別カバレッジを記録し、ユーザー投稿データは記録しない。

小さなロジック評価は `python eval/photo_place_evaluation.py` で実行する。`eval/fixtures/photo_place_synthetic.json` の架空POIと文章Clueを一時SQLite索引へ入れ、実際の `infer_photo_places` とcross-post候補生成を呼ぶ。写真bytes・公開地点画像・全国POI本体は使わない。評価器は画像fixtureを拒否し、ケースごとの独立注釈 `truth_kind` / `expected_place_ids` を予測結果と照合する。候補被覆率は識別可能な正解ケースのうち何らかのPOIが返った割合、正解候補率は同じ識別可能正解ケースを分母に正解 `place_id` が含まれた割合。unknown適合率は予測unknownのうち正解が曖昧またはunknownだった割合。曖昧GT単一断定率は曖昧正解ケースを分母に、単一candidateを返した割合。禁止位置claimは明示的にclaimを許可しないケースでの `residential_area` / `realtime_location` candidate件数と該当ケース率。削除経路脱落率は、陽性baselineからfixtureで指定した投稿を一件ずつ削除して全推論をやり直したチェックのうちclaimが消えた割合。分母ゼロ時は `null` とする。

このsynthetic結果は実在地点の候補被覆、行政階層誤差、写真検出/OCR/VLM精度、別角度照合、実地理索引の地域カバレッジを測らない。これらの実測は出典・ライセンス確認済みの索引と許諾済み評価画像が別途用意された後に別トラックで行う。手作りfixtureの成功率を本番精度として報告しない。

## 9. 段階的実装計画

1. **データ/権利棚卸し**: `data-prep/SOURCES.md` を基準に各地理データ、画像サービスの利用・キャッシュ・加工条件を確認する。全国の利用可能範囲と欠落地域を記録する。未確認のものは取り込まない。
2. **観測と共通型**: 既存OCR/VLM出力を再利用して `PhotoPlaceResult` / evidence/source IDを `common/` とweb型へ追加する。初期版はモックで、unknown/ambiguousも表現する。API/SSE契約を同じ変更で同期する。
3. **ローカル地理索引**: ライセンス条件が明確な全国地名/行政界/地物データを正規化し、SQLite R*Tree等の範囲検索または適切なローカル索引に入れる。全国画像を保管せず、候補生成と曖昧性判定を先に評価する。
4. **許諾済み参照画像照合**: 初期段階としてCommons GeoDataの位置付きファイルを、座標付き一意ローカルPOIと別診断同意から検索する。`CC0 1.0` / `CC BY 3.0` / `CC BY 4.0` のみ完全一致するlicense URLと作者を確認し、最大256px/512KiBのthumbnailを最大3枚、診断中のメモリで比較する。投稿写真は外部送信せず、pHash距離2bit以下とSSIM 0.985以上などの厳格な近似複製だけをreference evidenceとする。画像は保持しない。別角度の視点照合は別段階。
5. **外部補完（実装済み）**: 現行 `AGENTS.md` / `CLAUDE.md` / API契約を更新し、診断単位の専用同意、最大3 query、短いtimeout、テキストallowlist、mock transportテストを追加した。実請求APIは呼ばない。外部結果は未確認候補に留める。
6. **関係ルールと評価**: 写真場所候補を居住地推論から分離したまま、別投稿関係ルールを追加し、反例/削除再計算/未知ケースを評価する。実測前に確度を確率表示しない。
7. **API統合とリリース判断**: `docs/api-sse-contract.md`、共通スキーマ、web側検証、デモ表示を同期し、受け入れ基準とプライバシー試験を満たす範囲だけ有効化する。

## 10. 参考資料

- Mapillary, [CC BY-SA license for open data](https://help.mapillary.com/hc/en-us/articles/115001770409-CC-BY-SA-license-for-open-data), [An Introduction to Mapillary](https://help.mapillary.com/hc/en-us/articles/115001770269-An-Introduction-to-Mapillary)
- Wikimedia Commons, [Search by location](https://commons.wikimedia.org/wiki/Commons:Search_by_location), [Licenses](https://commons.wikimedia.org/wiki/Commons:Licenses)
- OpenStreetMap, [Copyright and license](https://www.openstreetmap.org/copyright)
- Overture Maps, [Places guide](https://docs.overturemaps.org/guides/places/), [Place schema](https://docs.overturemaps.org/schema/reference/places/place/), [getting data](https://docs.overturemaps.org/getting-data/), and [attribution](https://docs.overturemaps.org/attribution/)
- Existing data source registry: [`data-prep/SOURCES.md`](../data-prep/SOURCES.md)
- Existing API/SSE baseline: [`docs/api-sse-contract.md`](api-sse-contract.md)
- Brave Search API, [Place Search overview](https://api-dashboard.search.brave.com/documentation/services/place-search), [Place Search API reference](https://api-dashboard.search.brave.com/api-reference/web/place_search)

## 11. 実装状況（2026-11-14）

- **Commons参照画像（初期スライス）**: `COMMONS_REFERENCE_LOOKUP_ENABLED=1`、実モード、有限の日次診断上限、診断単位の独立同意 `photo_place_reference_consent` がそろう場合のみ実行する。一意で座標付きのローカルPOI候補だけをCommons GeoDataへ照会し、ファイルごとに厳密許可license URLと作者を検査する。CC0 1.0 / CC BY 3.0 / CC BY 4.0以外、作者/説明ページ/URLが欠けるものは取得しない。最大3地点/診断、最大3 thumbnail・512KiBずつ、API合計6要求まで。本人画像はBluesky CDNから対象画像1枚だけ4MiB上限で取り直し、Commonsへ画像/本文/IDを送らず、参照画像と比較バッファはメモリで処理して破棄する。参照証拠はpHash距離2bit以下、色付きSSIM 0.985以上、aspect ratio差0.005以内、低textureでない条件をすべて満たすときだけ追加する。画像取得のみでは証拠を付けず、候補status/score/`visible_in_frame`を変えない。一般の別角度認識は未実装。既定offでモックは通信しない。
- **共通型/API**: Python/TypeScriptのPhotoPlaceResult、出典・clue evidence検証を追加し、diagnoseの `conclusions` SSEとログインセッション内のメモリsnapshotに追加した。古いsnapshotではこのフィールドが省略されても復元できる。GET診断復元にも含む。
- **ローカル画像観測**: 駅は駅名OCRとVLMの重なった観測に既存駅Gazetteerの完全一致を要求する。郵便番号は既存Japan Post表に一致させる。施設/地標は写真の `shop/landmark/org_text/place_text` の明示名/aliasを共有normalizerで照合する。正規化キーの衝突は複数候補として `ambiguous` にする。`name_text` は人物名なので対象外。結果は `visible_in_frame` のみで、撮影地点やプロフィール位置には変換しない。
- **任意SQLite POI**: `data-prep/src/tkb_data_prep/import_places.py` はローカルGeoJSONLまたはPyArrowのバッチ読込に対応したGeoParquetを既存SQLite索引へ取り込む。GeoParquetでは `theme=places` と `type=place` の両partition列を必須にし、WKB Point、`addresses[].country=JP`、私有住居カテゴリdenylistを適用する。Overture [Place schema](https://docs.overturemaps.org/schema/reference/places/place/) と [Address schema](https://docs.overturemaps.org/schema/reference/places/types/address/) の `addresses[].locality` から、市区町村接尾辞で明示され一意な値だけを粗い `area_label` として保存する。公式定義上localityは近隣地区の場合もあるため、市区町村と判定できない値や競合値はnull。住所freeform・番地・郵便番号は保存しない。既存CLIと互換のためGeoJSONLが既定で、GeoParquetは `--input-format geoparquet` を指定する。API/Gazetteer既定ディレクトリは `data/processed/places.sqlite3`。既存DBは上書きしない。 Gazetteerは選択ディレクトリ直下の索引を優先し、`data/processed/national`が選択されて直下に索引がない場合だけ`data/processed/places.sqlite3`をfallbackとして使う。別の明示ディレクトリでは親へfallbackしない。Commons可用性判定もこの共通resolverと同じ索引schema versionを使う。`name_key` のindexでlookupする。索引がなければPOIはunknown。名称キーは `tkb_common.place_names.place_name_keys` をimport/search双方で共有し、NFKC、空白・中黒の差、かな文字種の差だけを正規化する。漢字の読みや意味は推測しない。SQLite `user_version` でキー仕様を示し、非対応versionは検索せずunknown理由を返すため、仕様更新後は索引を再生成する。公開POIデータのみ保存対象で、投稿画像・本文・診断結果は引き続き保存しない。DBレコードは `place_id, names/aliases, coordinates, area_label, basic_category/taxonomy, sources` を保持する。
- インポートは `addresses[].country=JP` を既定条件にする。住所国が欠落するデータは入力が日本範囲へ切り出し済みの場合だけ明示フラグで許可する（GeoParquetもcountry欠落行は除外）。`theme/type` が Places/place 以外のParquet行、Point以外、明示的な私有住居カテゴリは除外する。source licenseは各source行から保ち、null値は出典情報とともにDBに残すが検索aliasは作らない。`source-license-map` は人が確認したdataset別 SPDX mapping のみ受け付ける。POI名一致は未確認候補で、所在地の検証済み事実ではない。GeoParquetアダプタは小さなfixtureでpartition・国・私有カテゴリ・ライセンス・上書き条件を検証する。実データの取得量と地域カバレッジは取得前に別途確認する。
- 同名候補は最大50件を表示し、上限超過時は `too_many_matches` を付け、画面に候補の省略と曖昧さを示す。未校正scoreは保存型にあっても画面へ表示しない。
- **独立性と関係推論**: `photo_place_results` 自体はprofile claimではない。唯一の現行接続は `residential_area` への保守的な別推論で、ローカルlicensed POIの一意候補、同じ投稿本文の「自宅/家/うちの近くの候補名」、候補と画像Clue名の正規化一致、粗い `area_label`、別投稿の同地域 `PLACE_TEXT` と近隣/日常等の明示文脈をすべて要求する。`WEB_SEARCHED`候補、単なる地域名言及、引用/旅行/訪問/否定、曖昧候補は使わず、confidenceは最大0.65でstatusはweak。根拠経路に写真側・独立投稿側の両方を含め、除外・削除時は既存candidate-pool再評価で経路を落とす。表示する写真候補は削除投稿から除く。撮影地点/現在地推定は行わない。
- **Brave Place Search（実装済み）**: `api/src/tkb_api/photo_place_web.py` のtransport注入可能クライアント。診断ごとの `photo_place_web_lookup_consent` のみで起動し、既存ハンドル検索同意とは独立。最大3クエリ、画像OCR/VLM `shop/landmark/station_sign` の名称のみを送る。結果title完全一致と `postal_address.country=JP` を要求し、`source_url` は公開HTTPS検査後に表示。Brave短期ID/snippet/thumbnailは保持しない。mock・キーなしは通信しない。有料APIの実呼び出しは行っていない。
- **未実装**: 別角度を含む参照画像/視点照合、`camera_nearby` / `camera_at`の成立ルール、Braveなど外部候補の公式/公的な独立検証。国土数値情報P05 2022全国ZIPを取得し、役場・公的集会施設79,529件を47/47県でローカル索引化済み（SQLite 102,424,576 bytes、Gitignore対象）。P05は公的施設のみで、店舗等の全国施設網羅データではない。Overture PlacesのPOI本体は未取得。
- **Synthetic評価ハーネス**: `eval/photo_place_evaluation.py` は架空POI/文章Clueの小fixtureを実推論器に通し、候補被覆・正解POI候補率・unknown適合・曖昧単一断定・禁止位置claim・一件削除後の経路脱落を集計する。画像や公開地理データの実カバレッジを表すものではない。
- データ供給源の参照条件と任意取込手順は [`data-prep/SOURCES.md`](../data-prep/SOURCES.md)。API/SSE形は [`docs/api-sse-contract.md`](api-sse-contract.md)。テスト結果は実行環境での確認後に作業報告へ記録する。
