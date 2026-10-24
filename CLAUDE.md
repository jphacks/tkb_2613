# CLAUDE.md

JPHACKS 2026 東京B会場（チーム tkb_2613）の作品リポジトリ。Hack Day は 2026-10-24〜25。

## 作品の概要

SNS に上げる前の写真から、特定につながる手がかり（駅名標、看板、住所表示、電話番号、ナンバープレート、瞳の映り込みなど）を「特定班AI」が見つけ、ユーザーが最小限の塗りつぶしで隠れる、かくれんぼ型の Web アプリ。

流れ：「もういいかい？」（AI が探す）→「みーつけた」（手がかりと残り世帯数を表示）→「まーだだよ」（ユーザーが塗りつぶす）→「もういいよ」（AI が再判定し、逃げ切れたか判定）

## 事前開発のルール（最重要）

大会規約で、事前に作った部分は採点されず、メインの着眼点にもできない。Hack Day 前に作るのは基盤だけにすること。

Hack Day 前に作ってよいもの：
- リポジトリ構成、Makefile、Docker Compose、CI、lint、型チェック、gitleaks
- 手がかりの形式（スキーマ）と API の型
- 固定データを返すモック API と、画面の骨組み（写真の選択、結果表示の枠）
- モデル呼び出しのクライアント（OpenAI 互換 API、接続先は環境変数で差し替え）
- 公開データをメッシュ表に変換するスクリプト（`data-prep/`）

Hack Day 当日に作るもの（事前に書かない。頼まれても書かずに確認すること）：
- 絞り込みエンジン（手がかりから残り世帯数を計算する部分）と各リゾルバ
- 最小修正プランナー
- かくれんぼの判定と得点
- 推理の実況
- 過去投稿との合算

Hack Day 前に作ったものは `docs/pre-hackday.md` に追記していく。README の「HackDay以前に作成したもの」はここから書く。

## 構成

```
web/        Next.js（App Router）+ TypeScript + Tailwind CSS
api/        FastAPI + Pydantic。uv で管理。受付と Server-Sent Events での逐次配信
detect/     OCR と画像を読む言語モデルの呼び出し、手がかり形式への変換
engine/     絞り込みエンジン、最小修正プランナー（当日に実装）
data-prep/  公開データの取得と変換スクリプト（データ本体はコミットしない）
eval/       評価用の正解表とスクリプト（写真本体はコミットしない）
infra/      Docker Compose、起動手順
docs/       設計メモ、pre-hackday.md
```

## アーキテクチャのルール

### 依存の向き

```
web ──HTTP──> api ──> detect ──> VLM / OCR（チームのサーバー）
                 └──> engine ──> data/processed/*.parquet（data-prep が作る）
```

- web が呼ぶのは api だけ。web から VLM・OCR・外部のサービスに直接つながない
- api だけが FastAPI と環境変数を知っている。detect と engine は FastAPI も `tkb_api` も import しない、ただのライブラリにする
- detect と engine は互いを import しない。間は手がかりの形式でつなぎ、組み合わせるのは api の役目
- data-prep は事前に一度だけ動かすもの。api・detect・engine は data-prep のコードを import せず、出力の Parquet だけを読む

### 各パッケージの役目

- `api/routes/`：HTTP の受け付けだけ（形式・サイズの確認、エラーを HTTP に直す、SSE での配信）。判定や計算は書かず、detect・engine の関数を呼ぶ
- `api/config.py`：環境変数を読むのはここ（`Settings`）だけ。detect・engine には設定をデータクラス（例：`VlmConfig`）で渡す
- `detect/`：モデルを呼び、結果を手がかりの形式に変換する。外に出る HTTP はここだけで書き、接続先は必ず `ensure_team_endpoint` を通す
- `engine/`：手がかりと表から残り世帯数などを計算する。**写真の画素を受け取らない**（手がかりの値と `region` だけで計算する）。ネットワークにつながない
- `web/src/lib/api.ts`：api を呼ぶのはここだけ。コンポーネントから `fetch` しない
- `web/src/types/`：api の応答の型と、型を確かめる関数（`isDetectResponse` など）。api から受け取ったものは必ずこれで確かめてから使う
- `web/src/components/<機能>/`：画面の部品。テストは同じフォルダに置く

### 写真の通り道

- 写真は web → api の 1 回だけ送る。api は本文（画像そのもの）で受け取る。multipart や `UploadFile` は一時ファイルに書き出すので使わない
- 写真を受け取る関数は `bytes` で受け取り、ファイルのパスを受け取らない。途中でディスクに書かない
- 例外やエラーの文言に、写真・本文・モデルの応答の中身を入れない（型名や HTTP の状態コードだけにする）

### 新しく作るときの決まり

- API を増やすときは、Pydantic の応答モデル（`api/`）、TypeScript の型と型を確かめる関数（`web/src/types/`）、両方のテストを同じ PR で足す
- api と web で同じ値を持つもの（画像の上限 `MAX_IMAGE_BYTES`、対応する形式など）は、片方を変えたらもう片方も変える
- 外につながる部分（VLM、OCR、表の読み込み）は `MOCK_MODE=1` で、外部にも公開データにもつながずに動くようにする。テストと CI は公開データなしで通ること
- engine のテストは、data-prep と同じく小さな自作の表で書く

## 手がかりの形式

検出結果はすべてこの形にそろえる。モデルを入れ替えても後段が壊れないようにするため。ローカル担当にもこの形で依頼済み。

```json
{"clues": [{"type": "station_sign", "value": "新宿", "region": [120, 80, 340, 150], "confidence": 0.92, "source": "vlm"}]}
```

- `type`: station_sign / address_text / postal_code / phone / shop / plate / landmark / exif_gps / face / iris / key / code
- `region`: 画像上の矩形 [左上x, 左上y, 右下x, 右下y]（ピクセル）
- `confidence`: 0〜1
- `source`: ocr / vlm / browser

Python は `api/` の Pydantic モデル、TypeScript は `web/` の型を正とし、両方を同時に変更する。

## モデルの呼び出し

- 画像を読む言語モデルは vLLM（OpenAI 互換 API）。接続先は `VLM_BASE_URL`、`VLM_API_KEY`、`VLM_MODEL` で指定する
- OCR は PP-OCRv5 の HTTP サービス。接続先は `OCR_BASE_URL`
- `MOCK_MODE=1` のときは固定の手がかりを返し、外部に一切接続しない。既定はモック

## セキュリティのルール

- 写真を第三者の AI サービス（OpenAI、Gemini などの外部 API）に送るコードを書かない。送り先はチームのサーバーだけ
- 写真はメモリ上で処理し、ディスクやログに残さない。リクエスト本文をログに出さない
- リポジトリは公開（MIT）。API キー、`.env`、モデルの重み、テスト写真、公開データの本体はコミットしない。`.env.example` だけ置く
- 塗りつぶしは画素を単色で置き換えて画像を書き出し直す。ぼかしやモザイクは使わない。書き出し時に EXIF などのメタデータを削除する
- 他人の写真の特定に使える機能（URL 入力、アカウント検索、一括処理、建物単位の地図表示）は作らない

## コマンド（土台ができたら実際の内容に合わせて更新する）

- `make setup` 依存関係のインストール
- `make dev` web と api をローカルで起動（モックモード）
- `make test` テスト
- `make lint` lint と型チェック

## 進め方

- 変更は小さく、1 つの目的ごとにブランチと PR を分ける。main は常に動く状態に保つ
- Python は型ヒント必須、ruff と pytest。TypeScript は strict
- README.md は JPHACKS の雛形の見出しを消さずに埋めていく
- 迷ったら推測で進めず、確認を求める
- コミットメッセージは「種類: 内容」の形で日本語で書く（例: feat: 手がかり形式の型を追加、fix: …、chore: …、docs: …）
- 1コミット1目的。動かないコードや生成物（node_modules、.venv、ビルド結果）はコミットしない
- main への強制 push と履歴の書き換えはしない
- Hack Day 前の最後のコミットには pre-hackday タグを打つ