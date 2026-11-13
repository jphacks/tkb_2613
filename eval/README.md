# eval

検出の評価用の正解表とスクリプトを置く。

- 写真本体はコミットしない（`photos/` に置く。`.gitignore` 済み）
- 正解表は写真のファイル名と、手がかりの形式（`type` / `value` / `region`）で書く

## try_detect.py

手元の画像と本文から手がかりを取り出して表示する（試し用）。接続先はルートの `.env` から読む。

```bash
uv run python eval/try_detect.py eval/photos/a.jpg --text "夜勤明けのラーメン"
uv run python eval/try_detect.py --text "25歳になりました"
```

- `MOCK_MODE=1` のときは接続せず、空の一覧を表示する
- `--space relative_1000` / `--space sent_pixels` で座標の単位を一時的に指定できる（確認用）

## fixtures/demo_observations.json

架空のデモ用アカウント（架空の男性「はるき」、根津駅のまわり・文京区弥生二丁目に住む設定。メンバーの最寄りではない）の投稿10件と、そこから取り出した手がかり（手で作ったもの）。役割C の推理ルールの開発と、役割A の画面のモックに使う。

- `posts`：投稿（CLAUDE.md の「投稿」の形）。写真本体はない
- `clues`：手がかり（CLAUDE.md の「手がかり」の形）
- `annotation_kind: "manual"`：clue は手作業の注釈で、OCR/VLMの抽出結果ではない
- `expected`：この手がかりからそろうはずの推理と、その根拠の手がかりの番号（`clues` の添字）。最寄り駅・職業・名前と誕生日・決まった外出時間の4つ
- 推理に効かないおとりの手がかり（猫の瞳の映り込み、ジムの鏡に映ったロゴの一部）も混ぜてある
- 形式は `api/tests/test_demo_observations.py` で検査している

## 手元専用のモック投稿・画像

自分で用意した投稿と画像は `eval/local/` に置く。このディレクトリは `.gitignore` 対象なので、個人情報を含む内容をコミットしない。投稿は既存の `demo_observations.json` と同じトップレベル形式を使い、`posts` に標準の投稿フィールドを記載する。画像の `url` は共通型を満たすため `https://cdn.bsky.app/local-placeholder/<name>` のような文字列を置き、実際のローカル画像は任意の `local_file` で指定する。ファイルは `eval/local/images/` に保存し、`local_file` にはファイル名だけを書く。

```json
{
  "posts": [
    {
      "post_id": "at://did:plc:demo0000000000000000000/app.bsky.feed.post/3local001",
      "text": "投稿本文",
      "created_at": "2026-10-20T08:31:00+09:00",
      "images": [
        {
          "index": 0,
          "url": "https://cdn.bsky.app/local-placeholder/photo-1",
          "alt": "",
          "width": 1200,
          "height": 900,
          "local_file": "photo-1.jpg"
        }
      ]
    }
  ],
  "clues": []
}
```

`local_file` は `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.heif` のみ対応。ローカル画像は `MOCK_MODE=1` と `MOCK_LOCAL_ASSETS_ENABLED=1` の両方を設定したときだけ `/api/mock-assets/<file>` から配信される。既定では無効で、fixtureで参照したファイルだけを配信する。APIは fixture の隣の `images/` からファイル名のみで解決し、実モードではこの配信経路を拒否する。通常の `url` の `cdn.bsky.app` 検証も維持する。

`eval/local/demo_posts.json` を用意したら、ルート `.env` に次を設定してAPIを再起動する。

```dotenv
MOCK_MODE=1
DEMO_FIXTURE_PATH=eval/local/demo_posts.json
MOCK_LOCAL_ASSETS_ENABLED=1
```

画像を `eval/local/images/` に置く。パスは API の起動ディレクトリ（リポジトリルート）からの相対パスとして扱う。Compose (`make up`) は `eval/local/` を API コンテナへ読み取り専用でマウントする。設定がない場合は従来どおり `eval/fixtures/demo_observations.json` を使う。

## ローカル推理の前後比較

`mock_inference_report.py` は `posts` / `clues` を持つ既存fixtureまたは `eval/local/` の投稿データを、現在の `infer_owner_claims` と既存の `tkb_engine.infer` に通してJSONレポートにする。プロフィール推定は除外後の投稿・手がかりでも再実行する。除外は仮想比較で、Blueskyやモデルには接続せず、データも変更しない。

```bash
python eval/mock_inference_report.py
python eval/mock_inference_report.py eval/local/demo_posts.json --exclude at://did:plc:demo00000000000000000000/app.bsky.feed.post/3local000003
python eval/mock_inference_report.py eval/local/demo_posts.json --output eval/local/report.json
python eval/mock_inference_report.py eval/local/manual_fixture.json --truth eval/local/truth.json
```

手元データに任意の `truth` を付けるとプロフィール推定との照合を行う。`status: "confirmed"` の期待 claim のみ見逃しとして数える。`status: "provisional"` は未推定でも「未推定の暫定候補」と表示し、確認済みの失敗とは扱わない。完全性が確認されていない truth では未注釈候補を誤りと断定しない。claim の照合は `attribute` と `value` の完全一致。旧形式の Conclusion は別枠で出すが、truth 評価には使わない。

truth は fixture 内の `truth` フィールドでも、`--truth` で別ファイルでも渡せる。`status` は任意で `provisional` / `confirmed` を記録でき、レポートにも引き継ぐ。手作業で作った観測には fixture の `"annotation_kind": "manual"` を付けると、レポートに手動注釈であり OCR/VLM 結果ではないことが明記される。

```json
{
  "status": "provisional",
  "complete": false,
  "claims": [{"attribute": "residential_area", "value": "架空市"}]
}
```

## 候補集合の評価

`mock_inference_report.py` は、fixture に `candidate_sets` を含めるか、`--candidate-sets` に推論結果JSONを渡すと ProfileCandidateSet の評価を追加する。渡せるJSONは候補集合の配列、または `profile_claims` / `candidate_sets` 配列を持つオブジェクト。schema validation 後にレポートへ反映する。

`--provenance-scope` で `all`（既定）、`direct_disclosure`、`combined_inference`、`unclassified` のいずれかを選ぶと、その provenance の根拠経路を持つ表示候補だけを評価する。1つの候補に直接開示と複合推論の代替経路が両方あれば、両方のスコープに現れる。スコープは評価結果に記録される。精度指標は完全・確認済み truth を指定したときだけ計算され、この変更では正解率の再測定を行わない。

`candidate_status_rates` は入力された ProfileCandidateSet の status をそのまま数えた、未スコープの記述値。選択スコープ後の候補集合状態は `provenance_scoped_status_rates` に出す。対象 provenance の候補が0件なら `unknown`、1件なら `candidate`、2件以上なら `ambiguous` として数える。

```bash
python eval/mock_inference_report.py eval/local/manual_fixture.json --truth eval/local/truth.json --candidate-sets eval/local/candidate-sets.json
python eval/mock_inference_report.py eval/local/manual_fixture.json --truth eval/local/truth.json --candidate-sets eval/local/candidate-sets.json --provenance-scope combined_inference
```

```json
{
  "status": "confirmed",
  "complete": true,
  "claims": [
    {
      "attribute": "regular_station",
      "value": "根津駅",
      "evidence_paths": [[{"post_id": "at://…", "clue_index": 2}]]
    }
  ]
}
```

候補集合は `home_room` を除く24属性を一度ずつ含める必要がある。空配列、欠落属性、重複属性、余分な属性は採点前に拒否する。値は `candidate`（単独値）/ `ambiguous`（複数値）/ `unknown` / `conflict`。top-1 は正解値がある属性だけを分母にする。表示候補カバレッジは truth の期待値のうち候補集合に含まれた値の割合。誤候補率は完全・確認済み truth と照合できる場合に限り、表示された全候補値を分母として数える。unknown / conflict 率は24候補集合全体に対する記述統計で、truth が未確定でも出す。

候補集合の truth value 照合は NFKC 正規化・前後空白除去・`lower()` 後の完全一致で行い、意味的な同義表現は一致扱いしない（たとえば `Straße` と `STRASSE` は異なる値として扱う）。採点範囲は画面に出す `candidates` のみ。内部候補プール、rank、counter-evidence は採点に加えない。

truth claim に `evidence_paths` が付く場合は、予測の証拠経路との完全一致率に加えて、期待参照集合に対する参照 precision / recall を出す。完全一致は厳密な注釈一致指標。注釈にない追加参照は annotation precision を下げるが、それだけで事実に反する証拠とは判定しない。これらは注釈との一致度であり、根拠が意味的・因果的に推論を支持するかの判定ではない。別に出す evidence reference integrity は、`post_id` の存在、`clue_index` の範囲と投稿対応、画像番号、`web_fact_id` の存在を検査する。

レポートの `evaluation_track` は `annotation_kind` で区別する。`manual` は手作業で付けた観測上のルール評価、`detector` は OCR/VLM を含むエンドツーエンド評価、既定の `fixture` は観測元が明示されていない評価として扱う。手動注釈の結果をOCR/VLM精度として報告しないこと。

証拠は各状態の clue 配列に対する `clue_index` と投稿ID・種類・画像番号・領域・抽出元で示し、代替となる根拠経路を別々に保つ。本文や clue の値は証拠一覧に複製しない。地理テーブル `data/processed/` がない場合も他のルールを実行し、駅・住所などテーブル依存の推理は利用できない。`geographic_tables` には駅・郵便番号・メッシュ・学校の各表の利用可否を出す。`--output` は `.gitignore` 済みの `eval/local/` 以下だけに書き込める。

## X1 の投稿横断デモ

`eval/demo_account/x1_posts.json` は、駅を別々の投稿で2回、学校名を別投稿で1回、家から通学している話をさらに別投稿で1回出す4件の投稿案。X1 は生活圏と学校を結び、経路や時刻は推定しない。`eval/fixtures/demo_x1.json` は同じ本文に手作業で期待する手がかりを付けたモック用データ。`DEMO_FIXTURE_PATH=eval/fixtures/demo_x1.json` を指定してモック診断で確認できる。実投稿は `eval/demo_account/post_x1.py` の `--publish` で行い、同文投稿は重複させない。

## fixtures/demo_layered.json（居住地域の経路を重ねるデモ）

子どものいる架空の保護者のアカウント9件。ゴミの日・子どもの学校・避難所・バス停の4つの経路が、どれも文京区千駄木を指すように作った（学校・避難所・バス停の名前は公開データの表にある実在のもの、行事名「あおぞらフェスタ」と人物は架空）。`DEMO_FIXTURE_PATH=eval/fixtures/demo_layered.json` でモック診断に使える。実際に出る結論は `engine/tests/test_demo_layered.py` で固定している。

- R5（収集地区）：住所の一部「文京区千駄木x丁目」と土曜朝の「燃えるゴミ出し忘れた」で `文京区 千駄木3～5丁目`
- 居住地域（residential_area）：避難所（千駄木小学校）・バス停（千駄木三丁目、都営バス）・子どもの学校（林町小学校）の学区の3経路が `文京区` で重なる。確からしさは経路の最大（0.65、weak）
- 避難所・バス停・学区の表は区市町村までしか持たないので、町まで重なるのは R5 だけ
