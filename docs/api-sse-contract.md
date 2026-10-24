# 現行 API・SSE 契約と担当境界

この文書は `main` の実装を記録する。実装前の企画書や AGENTS.md にある目標仕様とは区別し、ここにない機能は実装済みとして扱わない。

## 対象と共通動作

- api は FastAPI、画面からは同一オリジンの `/api` を使う。Next.js は `API_ORIGIN`（既定 `http://localhost:8001`）へ `/api/:path*` を中継する。
- api の応答は `Cache-Control: no-store`。SSE にはさらに `X-Accel-Buffering: no` が付き、イベント間が設定値 `SSE_KEEPALIVE_SECONDS`（既定15秒）以上空くと `: keep-alive` コメントが流れる。コメントは画面で読み飛ばす。
- セッション Cookie 名は `tkb_session`。値はランダムなセッションID。Bluesky のセッション情報は api プロセスのメモリ上にあり、既定30分で失効する。
- `MOCK_MODE=1` が既定。モックログインは架空DIDを使い、Blueskyへ接続しない。モック診断は `eval/fixtures/demo_observations.json` を再生し、モデルにも接続しない。
- `MOCK_MODE=0` の診断では、セッションの DID の本人投稿だけを新しい順に最大 `MAX_POSTS` 件（既定30、設定上限100）取得する。

## エンドポイント一覧

| メソッド・パス | リクエスト | 成功応答 | 実装上の注意 |
| --- | --- | --- | --- |
| `GET /health` | なし | `{"status":"ok","mock_mode":true}`（値は設定による） | 認証不要。生存確認用。 |
| `POST /api/session` | JSON `{"handle":"name.example","password":"…"}` | 200 `{"handle":"…","did":"did:…"}` と `tkb_session` Cookie | `handle` はtrimし先頭の `@` を1つ除去。空handle/passwordは422。実ログイン失敗は401、Bluesky接続失敗は502。モック時は入力handleと固定DIDでログイン扱い。 |
| `GET /api/session` | `tkb_session` Cookie | 200 `{"handle":"…","did":"did:…"}` | Cookie欠落・無効・期限切れは401 `{"detail":"ログインしてください"}`。 |
| `DELETE /api/session` | `tkb_session` Cookie | 204、Cookie削除 | セッションがなくても204。 |
| `POST /api/detect` | 画像バイナリをリクエスト本文に直接送信。許可Content-Type: JPEG/PNG/WebP/HEIC/HEIF | モック時200 `{"clues":[…]}` | 空本文400、未対応形式415、20MiB超413。`MOCK_MODE=0` は現状501「検出はまだ実装されていません」。このルートはログイン必須ではない。 |
| `POST /api/diagnose` | `tkb_session` Cookie。JSON bodyなし | `text/event-stream` | Cookieなし・無効は401。成功時は以下のSSE順序。投稿/手がかり/結論の結果はサーバーに保存しない。 |

バリデーションエラーは422で `{"detail":[{"loc":[…],"msg":"…","type":"…"}]}` を返す。送信値そのものは詳細に含めない。その他のエラー形式は FastAPI のHTTPエラー応答に従う。

## 共通データ型

Pythonの正は `common/src/tkb_common/schemas.py`、画面側の対応型は `web/src/types/`。

- **Post**: `post_id`（AT URI）、`text`、時差付き `created_at`、`images`。画像は `index, url, alt, width, height`。URLは `https://cdn.bsky.app/` のみ、画像は最大4枚。
- **Clue**: `post_id, image_index, type, value, region, confidence, source`。`region` は元画像ピクセルの `[x1,y1,x2,y2]` またはnull。本文由来は通常 `image_index/region=null`、`source=text`。確信度は0〜1。許容type/sourceの列挙と写真/本文の整合条件は共通スキーマを参照。
- **DetectResponse**: `{"clues":[Clue,…]}`。
- **現在の診断Conclusion**: `rule, attribute, value, clue_indices, note`。`clue_indices` は同じ `conclusions` イベントの `clues` 配列に対する0始まり番号。これは目標の16項目プロフィール型（status/confidence/evidence）とは別の試作型。

## 診断 SSE のイベント

SSEブロックは `event: <name>\ndata: <JSON>\n\n`。JSONはUTF-8で送られる。

| 順序 | event | data | 発生タイミング |
| --- | --- | --- | --- |
| 1 | `post` | `{"post": Post}` | 診断対象投稿をすべて取得した後、投稿一覧の順に全件送信。各投稿を送るたび手がかり抽出を待つわけではない。 |
| 2 | `clues` | `{"post_id":"…","clues":[Clue,…],"error":string|null}` | 抽出処理が完了した投稿ごと。抽出処理の完了順。成功時は `error:null`。投稿単位の抽出失敗時は空の `clues` とエラー文字列を送る。 |
| 3 | `conclusions` | `{"clues":[全Clue,…],"conclusions":[Conclusion,…]}` | 全投稿の抽出処理の後に1回。cluesは `clues` イベントで得た配列を集めたもの。 |
| 4 | `done` | `{"posts_seen":number}` | 推理の後、正常完了時に1回。 |

### 失敗・切断の現状

- 投稿単位の抽出失敗は `clues.error` に載る。現行パイプラインはその後も残りの処理を続け、集まった手がかりで `conclusions`、続けて `done` を送る。したがって `done` は全投稿の抽出成功を意味しない。
- `post`、抽出器の準備、Bluesky投稿取得など診断全体の失敗は、ストリーム開始前なら通常のHTTPエラー（例: 401/502/503）。ストリーム開始後に起きた例外を表す専用 `error` SSE イベントは現行実装・型にない。接続が途中終了すれば画面側は `done` 不達として「診断の途中で接続が切れました」とエラー表示する。
- クライアントは未知のイベント名を無視し、既知イベントの不正な形は不正応答として扱う。`done` 前の正常なEOFも切断エラー。
- 再実行開始時、画面は前回の投稿・手がかり・結論をクリアする。画面離脱時は AbortController で通信を中断する。
- SSEのイベント順序や部分失敗時の画面表現をさらに整える作業は Issue #46 の範囲。

## 担当境界とデータ受け渡し

担当記号はIssueの記述にあるA/B/C/Dを使い、個人名やIssueにない合意内容は補わない。

| 担当 | 現在の責務・境界 | 主な受け渡し |
| --- | --- | --- |
| A | Web画面・操作・結果表示。APIとの通信、型検証、診断中の状態表示を担当。 | `web/src/types` の `Post`, `Clue`, `DiagnoseEvent`, `SessionResponse` と `web/src/lib/api.ts` を介してJSON/SSEを受け取る。Aの仮除外比較画面はIssue #69。 |
| B | 投稿単位の写真/本文から観測手がかりを抽出する担当範囲（Issue #60）。現行 `detect/` は抽出器・OCR/VLMクライアントを持つ。 | 入力は`Post`と画像bytes、出力は `PostExtraction(post_id, clues: Clue[])`。api pipelineが受け取りSSE `clues` と `conclusions.clues` へ渡す。独立 `POST /api/detect` の本番処理は未実装。 |
| C | 手がかりからの推理ルール、プロフィール推定・削除前後計算の担当範囲（Issue #59/#61/#65）。 | 入力は `Clue[]`、`Post[]`、必要な地名辞書。現行 `engine` の `infer` は試作 `Conclusion[]` を返し、`clue_indices` で入力Clueを参照。共通16項目型と削除プランナーは未接続。 |
| D | API、Bluesky本人セッション/投稿取得、診断パイプライン、各担当間の統合（Issue #38/#40/#45/#48）。 | Cookie付きHTTPを受け、`Post[]`→Bの抽出→`Clue[]`→Cの推理→SSEイベントとしてAへ渡す。シミュレーションAPIはIssue #48の後続で、現行にはない。 |

**依存の流れ:** A ⇄ D(API/SSE) → B(抽出) → D(集約) → C(推理) → D(SSE) → A(表示)。型の共有元はPythonでは`common/`、TypeScriptでは`web/src/types/`。API固有のログイン要求/応答は `api/src/tkb_api/schemas.py` と `web/src/types/session.ts` で対応する。

## まだ実装されていない目標機能

- 16項目プロフィールの `found/weak/unknown`、確からしさ、根拠を含む共通出力（現行は試作Conclusion）。
- 投稿の削除候補プランナー、選択投稿の仮除外・再推定API、実投稿の削除API。
- Blueskyログイン時以外の本番画像/本文抽出の統合完了確認。独立detectエンドポイントはモックのみで、本番は501。
- SSEの全体失敗イベント、途中切断後の再開・再送プロトコル。

これらはAGENTS.mdの目標やIssueの後続範囲であり、この文書の現行契約には含めない。
