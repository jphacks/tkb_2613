# detect

投稿1件から手がかり（見えたもの・書いてあるもの）を取り出す。推理はしない（推理は engine の推理ルール）。

- `Extractor.extract_post(post, images)`：投稿と、その写真のバイト列（`post.images` と同じ順）から `list[Clue]` を返す
  - 写真：長い辺を1280pxに縮めた JPEG（メタデータなし）を VLM に送る。座標は元の画像のピクセルに直す
  - 本文：本文だけを VLM に送る。`<post>` と `</post>` で囲み、本文の中の区切りは崩す
  - どちらも `response_format`（json_schema）で手がかりの JSON だけを返させ、形の合わない項目は捨てる
  - 画像は呼び出し側（api）が `cdn.bsky.app` から取ってきて渡す。detect が接続するのは vLLM と OCR だけ
- `extract_posts(extractor, posts, fetch_images)`：投稿をまとめて処理する非同期ジェネレーター。診断の SSE から `async for` でそのまま使う
  - 4件ずつ並列に `extract_post` を実行し、終わった順に `PostExtraction`（`post_id`・`clues`・`error`）を返す。`model_dump(mode="json")` がそのまま SSE の data になる
  - 1件が失敗しても止めず、その投稿だけ `error` に理由を入れる（投稿の中身は入れない）
  - `fetch_images(post)` は呼び出し側（api）が渡す。写真のない投稿では呼ばない
  - 受け取り側が途中でやめたら（`aclose()`、SSE が切れたとき）、残りの処理を取り消す
- `build_extractor(...)`：設定から作る。`OCR_BASE_URL` が空かモックのときは OCR を使わない
- `VlmClient`：vLLM（OpenAI 互換 `POST {VLM_BASE_URL}/chat/completions`）。毎回思考モードを切る（`enable_thinking: false`）。接続の段階の失敗（名前解決の失敗など）だけ、2回まで送り直す
- `OcrClient`：PP-OCRv5。PaddleX の OCR サービス形式（`POST {OCR_BASE_URL}/ocr`）を想定。OCR の箱が VLM の手がかりと重なれば位置は OCR を使い、郵便番号と電話番号は正規表現でも拾う
- `mock_mode=True`（既定）のときは接続せず、手がかりは空
- 接続先は `ensure_team_endpoint` で確認し、第三者の AI サービス（OpenAI、Gemini など）は拒否する
- 型は `tkb_common.schemas`（`Post`、`Clue`）を使う。api は import しない（循環依存になるため）

## 座標の単位

qwen3.6-27b は、画像の大きさによらず 0〜1000 の相対値で返す（2026-10-24 に合成画像で確認）。
`coords.COORDINATE_SPACE = RELATIVE_1000` にして、元の画像のピクセルに直している。
モデルを替えたら確かめ直すこと（`eval/try_detect.py --space` で切り替えて試せる）。
