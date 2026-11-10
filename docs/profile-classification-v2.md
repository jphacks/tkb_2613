# プロフィール候補とプライバシー分類 v2

プロフィールの候補IDは `common/src/tkb_common/schemas.py` と `web/src/types/profile.ts` で同期する。既存16項目のうち混在していた8項目を分解し、残り8項目は維持したため候補は計25件となる。分割前のIDは候補IDとして使用しない。

| 分割前 | 新しい候補ID |
| --- | --- |
| given_name_or_nickname | given_name / nickname |
| home_building_or_room | home_building / home_room |
| commute_station_or_line | home_nearest_station / regular_station / regular_line |
| long_term_home_absence | announced_long_absence / actual_home_absence |
| workplace | employer_name / workplace_building_candidate |
| vehicle_model_or_partial_plate | vehicle_model / partial_plate |
| partner_status_and_attributes | partner_status / partner_attributes |
| children_age_and_school | child_age / child_school |

## Claim assessment

分類は項目のカタログではなく、主張とその根拠経路ごとに付ける。`ClaimAssessment` は以下を保持する。

- `minimal_scope`: bluesky / bluesky_plus_public_web / bluesky_plus_offline。オフラインの場合は `offline_subtype` に観察・接触などの経路を書く。
- `psychological_resistance`: 1〜5。`persona_context` に本人の公開範囲やペルソナなど、評価時の文脈を記す。
- `inference_ease`: 1〜5 と `inference_ease_basis`（provisional / measured）。これは手がかり検出の `confidence` と別の指標。
- `harm_severity`: 1〜5 と具体的な `harm_scenario`、成立条件 `harm_prerequisites`、`harm_status`。

根拠がないスコアは `null` にする。成立条件がそろっていない場合は `prerequisites_unmet` を使い、現在の被害が発生しているとは表示しない。プロフィールの `confidence` は分類スコアではない。

## 推論境界

現行アプリはログイン中の本人のBluesky投稿と、そのセッションDIDのプロフィール文だけを取得する。プロフィール文の抽出結果は自己申告として別枠表示し、通常の投稿手がかりに混ぜない。限定推論にプロフィール文が使われる場合も、根拠は `source=profile_text` として投稿本文とは明確に分ける。他SNS等の横断データ取得は行わない。

`residential_area` と `employer_name` は、投稿内の本人関係アンカーまたはプロフィール文の自己申告アンカー、明示的な橋渡し、型付きの具体値がそろう場合に限る。プロフィール文をアンカーに使う場合も、橋渡しと値を示す独立した2件の投稿が必要。単独の住所や駅から居住地を決めたり、ロゴや訪問だけから勤務先を決めたりしない。推定結果は投稿テキスト範囲・型付き手がかり・必要ならプロフィール文範囲を証拠経路に含め、削除後は削除投稿を参照する経路を除いて再計算する。プロフィール文の根拠自体は投稿削除では消えないが、2投稿の条件を満たす経路がなくなれば推定は消える。

既存のBluesky内だけの経路で実装する日本語形は、居住地の「自宅近くのX」＋別投稿の「XはY」、雇用主の「うちの会社のX」＋別投稿の「YのX」。Yには本文またはプロフィール文の一致する型付き `place_text` / `org_text` 手がかりと限定語尾検証を要求する。「商店街」「研修」のような一般名詞だけの橋渡し、型付き手がかりがない場合、曖昧・競合する値は候補を出さない。プロフィール文を値に使う場合も、アンカーと橋渡しを示す別々の投稿が2件必要。

勤務先名には、公開Web上の組織自体の正式名称を使う追加経路を設けた。投稿Aで「勤務先はX」「勤め先はX」「うちの会社はX」のようにX自体を雇用主として明示し、別投稿Bでも同じ固有名Xに触れ、WebFactの `subject=X, relation=legal_name_of, object=Y` がそろう場合だけ、Yを弱い候補にする。「うちの会社のX」ではXが子会社・研修・施設などを指す可能性があるためWeb経路の本人アンカーとして扱わない。Xに関係する研修・イベント・施設の主催や運営情報からも勤務先を導かない。WebFactは本人の勤務関係を証明しない。同名・競合する組織名、訪問・見学文脈は棄却し、投稿を削除した後はWebFactだけで候補を残さない。実モードのWeb検索は未接続であり、現状では固定WebFactを渡した場合だけこの経路が動く。
