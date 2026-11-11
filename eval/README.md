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

手元データに任意の `truth` を付けるとプロフィール推定との照合を行う。`status: "confirmed"` の期待 claim のみ見逃しとして数える。`status: "provisional"` は未推定でも「未推定の暫定候補」と表示し、確認済みの失敗とは扱わない。未注釈の推定を false positive とするのは `status: "confirmed"` かつ `complete: true` の場合だけ。claim の照合は `attribute` と `value` の完全一致。旧形式の Conclusion は別枠で出すが、truth 評価には使わない。

truth は fixture 内の `truth` フィールドでも、`--truth` で別ファイルでも渡せる。`status` は任意で `provisional` / `confirmed` を記録でき、レポートにも引き継ぐ。手作業で作った観測には fixture の `"annotation_kind": "manual"` を付けると、レポートに手動注釈であり OCR/VLM 結果ではないことが明記される。

```json
{
  "status": "provisional",
  "complete": false,
  "claims": [{"attribute": "residential_area", "value": "架空市"}]
}
```

証拠は各状態の clue 配列に対する `clue_index` と投稿ID・種類・画像番号・領域・抽出元で示し、代替となる根拠経路を別々に保つ。本文や clue の値は証拠一覧に複製しない。地理テーブル `data/processed/` がない場合も他のルールを実行し、駅・住所などテーブル依存の推理は利用できない。`geographic_tables` には駅・郵便番号・メッシュ・学校の各表の利用可否を出す。`--output` は `.gitignore` 済みの `eval/local/` 以下だけに書き込める。

## X1 の投稿横断デモ

`eval/demo_account/x1_posts.json` は、駅を別々の投稿で2回、学校名を別投稿で1回、家から通学している話をさらに別投稿で1回出す4件の投稿案。X1 は生活圏と学校を結び、経路や時刻は推定しない。`eval/fixtures/demo_x1.json` は同じ本文に手作業で期待する手がかりを付けたモック用データ。`DEMO_FIXTURE_PATH=eval/fixtures/demo_x1.json` を指定してモック診断で確認できる。実投稿は `eval/demo_account/post_x1.py` の `--publish` で行い、同文投稿は重複させない。
