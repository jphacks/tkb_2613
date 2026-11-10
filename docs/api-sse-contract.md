# 現行 API・SSE 契約と担当境界

この文書は現在のブランチの実装を記録する。実装前の企画書や AGENTS.md にある目標仕様とは区別し、ここにない機能は実装済みとして扱わない。

## 対象と共通動作

- api は FastAPI、画面からは同一オリジンの `/api` を使う。Next.js は `API_ORIGIN`（既定 `http://localhost:8001`）へ `/api/:path*` を中継する。
- api の応答は `Cache-Control: no-store`。SSE にはさらに `X-Accel-Buffering: no` が付き、イベント間が設定値 `SSE_KEEPALIVE_SECONDS`（既定15秒）以上空くと `: keep-alive` コメントが流れる。コメントは画面で読み飛ばす。
- セッション Cookie 名は `tkb_session`。値はランダムなセッションID。Bluesky のセッション情報は api プロセスのメモリ上にあり、既定30分で失効する。
- `MOCK_MODE=1` が既定。モックログインは架空DIDを使い、Blueskyへ接続しない。モック診断は `eval/fixtures/demo_observations.json` を再生し、モデルにも接続しない。
- `MOCK_MODE=0` の診断では、セッションの DID の本人投稿だけを新しい順に最大 `MAX_POSTS` 件（既定30、設定上限100）取得し、同じセッション DID のプロフィール文も取得する。

## エンドポイント一覧

| メソッド・パス | リクエスト | 成功応答 | 実装上の注意 |
| --- | --- | --- | --- |
| `GET /health` | なし | `{"status":"ok","mock_mode":true}`（値は設定による） | 認証不要。生存確認用。 |
| `POST /api/session` | JSON `{"handle":"name.example","password":"…"}` | 200 `{"handle":"…","did":"did:…"}` と `tkb_session` Cookie | `handle` はtrimし先頭の `@` を1つ除去。空handle/passwordは422。実ログイン失敗は401、Bluesky接続失敗は502。モック時は入力handleと固定DIDでログイン扱い。 |
| `GET /api/session` | `tkb_session` Cookie | 200 `{"handle":"…","did":"did:…"}` | Cookie欠落・無効・期限切れは401 `{"detail":"ログインしてください"}`。 |
| `DELETE /api/session` | `tkb_session` Cookie | 204、Cookie削除 | セッションがなくても204。 |
| `POST /api/detect` | 画像バイナリをリクエスト本文に直接送信。許可Content-Type: JPEG/PNG/WebP/HEIC/HEIF | モック時200 `{"clues":[…]}` | 空本文400、未対応形式415、20MiB超413。`MOCK_MODE=0` は現状501「検出はまだ実装されていません」。このルートはログイン必須ではない。 |
| `POST /api/draft-check` | Cookie認証。JSON `{"text":"…","photo_base64":string|null,"photo_content_type":string|null}`。写真なしでは両写真フィールドをnullにする | 200 `{"posts_checked":number,"overlaps":[{"clue":Clue,"evidence":[{"post_id":"…","created_at":"…"}]}],"mock_mode":boolean,"notices":[string,…]}` | 認証必須。実モードではセッション本人の投稿だけを取得し、DID外の投稿URIも除外する。下書きと既存投稿を同じ抽出器で観測し、typeとUnicode NFKC・英字大小・連続空白だけを正規化した値が一致する手がかりだけ返す。推理エンジンと投稿時刻ベースの推理は呼ばない。本文最大10,000文字、画像20MiB、ストリーム読込JSON本文30MiB。画像はbase64 JSONで受け、multipartの一時ファイルを避ける。内容とContent-Typeの一致、画像デコード、画素数を確認する。入力・結果を保存/ログ記録しない。`MOCK_MODE=1` は固定の架空投稿を使い、source=textの固定手がかり文字列をNFKC・casefold・空白圧縮後に下書き本文から部分一致で探すだけ。下書きの抽出結果や意味判定を示さず、写真は解析しない旨を `notices` で返す。 |
| `POST /api/diagnose` | `tkb_session` Cookie。JSON bodyなし | `text/event-stream` | Cookieなし・無効は401。成功時は以下のSSE順序。投稿/手がかり/結論の結果はサーバーに保存しない。 |

バリデーションエラーは422で `{"detail":[{"loc":[…],"msg":"…","type":"…"}]}` を返す。送信値そのものは詳細に含めない。その他のエラー形式は FastAPI のHTTPエラー応答に従う。

## 共通データ型

Pythonの正は `common/src/tkb_common/schemas.py`、画面側の対応型は `web/src/types/`。

- **Post**: `post_id`（AT URI）、`text`、時差付き `created_at`、`images`。画像は `index, url, alt, width, height`。URLは `https://cdn.bsky.app/` のみ、画像は最大4枚。
- **Clue**: `post_id, image_index, type, value, region, confidence, source`。`region` は元画像ピクセルの `[x1,y1,x2,y2]` またはnull。本文由来は通常 `image_index/region=null`、`source=text`。画像alt由来は `source=alt` と画像の `image_index` を持ち、矩形はnull。プロフィール文由来の自己申告は `source=profile_text`。確信度は0〜1。許容type/sourceの列挙と整合条件は共通スキーマを参照。
- OCRはGazetteerの実在駅名に完全一致し、確度0.8以上・矩形ありの行について、同じ画像の `station_sign` / `source=vlm` が同一の駅名と重なる矩形を示す場合だけ `station_sign` / `source=ocr` を出す。`regular_station` 推定でもOCR/VLM両方のclueを必須根拠にし、OCRだけの文字列一致やVLMだけの視覚判断は候補にしない。同じ駅名のOCR/VLM clueは両方保持する。
- `detect` はOCRの同一行が厳密な「Y社のX」または「株式会社YのX」の形で確度0.8以上なら、全文を `org_text` / `source=ocr` の観測手がかりとして出し、元画像ピクセルのregionを付ける。この観測から本人の勤務先は推定しない。
- **DetectResponse**: `{"clues":[Clue,…]}`。
- **現在の診断Conclusion**: `rule, attribute, value, clue_indices, note`。`clue_indices` は同じ `conclusions` イベントの `clues` 配列に対する0始まり番号。
- **ProfileItem**: `attribute, value, confidence, status, evidence, evidence_paths, assessment`。現在は `residential_area`, `regular_station`, `employer_name`, `child_age` の限定ルールのみが生成する。`ProfileEvidence.source=public_web` のときは `web_fact_id` を参照し、投稿IDは持たない。評価軸の詳細は `docs/profile-classification-v2.md` を参照。
- **WebFact**: `id, subject, relation, object, source_url, source_title, source_kind, excerpt, retrieved_at, verification_status`。公開対象物についての事実であり、本人との関係そのものは示さない。雇用主名のWeb補強では `relation=legal_name_of` の確認済み公式組織・公的登録情報だけを受け付け、本人投稿で明示された会社名自体を `subject` にする。研修・イベント・施設の主催、運営、開催場所などから雇用主を結び付けない。SSE内の各 `public_web` 根拠は同じイベントの `web_facts[].id` に存在し、ID重複や参照切れはクライアントが不正応答として拒否する。

## 診断 SSE のイベント

SSEブロックは `event: <name>\ndata: <JSON>\n\n`。JSONはUTF-8で送られる。

| 順序 | event | data | 発生タイミング |
| --- | --- | --- | --- |
| 1 | `post` | `{"post": Post}` | 診断対象投稿をすべて取得した後、投稿一覧の順に全件送信。各投稿を送るたび手がかり抽出を待つわけではない。 |
| 2 | `clues` | `{"post_id":"…","clues":[Clue,…],"error":string|null}` | 抽出処理が完了した投稿ごと。抽出処理の完了順。成功時は `error:null`。投稿単位の抽出失敗時は空の `clues` とエラー文字列を送る。 |
| 3 | `conclusions` | `{"clues":[全Clue,…],"conclusions":[Conclusion,…],"profile_claims":[ProfileItem,…],"web_facts":[WebFact,…],"web_lookup_status":"not_run"|"fixture","owner_profile_text":string,"self_report_clues":[Clue,…]}` | 全投稿の抽出処理の後に1回。cluesは `clues` イベントで得た配列を集めたもの。profile_claims は限定ルールで成立した候補。プロフィール文と自己申告手がかりは別枠で返す。`fixture` は架空の固定WebFactを使用、`not_run` は公開Web未照合を示す。画面では `profile_claims` を主たるプライバシー推定として表示し、空の場合は「現行ルールで候補が成立しない」と伝える（安全の確認とは表現しない）。`conclusions` は既存クライアント互換のため送るが、R1〜R3試作候補として折りたたみ、検証済みの事実として提示しない。 |
| 4 | `done` | `{"posts_seen":number}` | 推理の後、正常完了時に1回。 |

### 失敗・切断の現状

- 投稿単位の抽出失敗は `clues.error` に載る。現行パイプラインはその後も残りの処理を続け、集まった手がかりで `conclusions`、続けて `done` を送る。したがって `done` は全投稿の抽出成功を意味しない。
- プロフィール文・投稿取得またはモデル初期化に失敗した場合、SSE開始前に通常のHTTPエラーを返す。
- `post`、抽出器の準備、Bluesky投稿取得など診断全体の失敗は、ストリーム開始前なら通常のHTTPエラー（例: 401/502/503）。ストリーム開始後に起きた例外を表す専用 `error` SSE イベントは現行実装・型にない。接続が途中終了すれば画面側は `done` 不達として「診断の途中で接続が切れました」とエラー表示する。
- クライアントは未知のイベント名を無視し、既知イベントの不正な形は不正応答として扱う。`done` 前の正常なEOFも切断エラー。
- 再実行開始時、画面は前回の投稿・手がかり・結論をクリアする。画面離脱時は AbortController で通信を中断する。
- SSEのイベント順序や部分失敗時の画面表現をさらに整える作業は Issue #46 の範囲。

### `profile_claims` の範囲

- 現在の限定推論対象は `residential_area`, `regular_station`, `employer_name`, `child_age`。明示的な本人関係、固有名の橋渡し、型付き値がそろった場合だけ候補を返す。単独の住所・駅名、一般名詞、ロゴ、訪問だけでは推定しない。`child_age` は同じ子の識別的な名前と親子関係を明示した別々の本人投稿を必要とし、Aの生年とBの明示的な「今日は/本日は誕生日」およびBの日本時間投稿日から診断日時点の満年齢（0〜17歳）を計算する。診断日は通常JST現在日付で、関数引数から固定日を注入できる。引用・創作・第三者、複数の生年/誕生日経路、別投稿で既に明示された年齢、うるう日、未来日、18歳以上などは棄却する。証拠経路は両投稿を必須にするため、どちらかを除くと正確な年齢は失効する。ただし生年の記載自体は削除しない限り残る。
- `regular_station` は駅名を含まない通勤習慣を明示する本人投稿Aと、別投稿B本文の「いつもの通勤駅から」等の文脈、Bの写真にある一意・完全・高確度なOCR駅名、および同じ画像内で同名・領域重複するVLM `station_sign` 観測、Gazetteer掲載駅名がすべて一致したときだけ弱い候補にする。B内の隣駅を含む複数駅名、部分値（x）、OCR/VLMの片方のみ、矩形なし・非重複、訪問文脈、駅データ未掲載は棄却する。両投稿本文とroutine_textがあればその手がかり、OCR/VLM clueを必須根拠とし、削除時は経路を崩す。駅名を既に書いた習慣投稿は、この経路のアンカーにしない。
- Bluesky内の `employer_name` 所有格経路（「うちの会社のX」＋「YのX」）は、Xが施設・事業・委託対象の可能性を排除できないため停止した。Web legal-name経路は別投稿で本人が勤務先Xを明示し、別投稿と検証済み公式情報でXの正式名Yを補強する既存条件のまま維持する。
- 診断APIは同じGazetteerをOCR抽出器と推論器へ渡す。station clueの `clue_index` は他のprofile evidenceと同じく `conclusions.clues` 全体配列を参照する。
- `employer_name` には、別投稿の固有名の橋と確認済みWebFactを結んだ経路も追加できる。Web経路の本人アンカーは「勤務先はX」「勤め先はX」「うちの会社はX」のようにX自体を雇用主として明示する文に限る。「うちの会社のX」は子会社・研修・施設などを指す可能性があるためWeb経路のアンカーにしない。WebFactはX自体の正式名称（`subject=X`, `relation=legal_name_of`, `object=正式名称`）だけを補強し、Xに関連する研修・イベント等の事実から雇用関係を推論しない。本人投稿2件の条件を維持し、訪問・見学文脈、競合する会社名は採用しない。これは推論器と固定データの受け口であり、実モードの公開Web検索接続は未実装。実モードでは `web_facts=[]`, `web_lookup_status=not_run`。
- 推論パターン確度は暫定値で校正済み確率ではない。0.50未満は出さず、0.80未満を `weak`、0.80以上を `found` とする。
- `evidence_paths` はAND条件の経路ごとに根拠を列挙し、複数経路はORとして扱う。削除後は削除投稿を含む経路を除いて再計算する。プロフィール文根拠は `source=profile_text` と抜粋で区別する。
- 四軸評価の未根拠値はnull。条件付き危害はシナリオ・前提条件・状態がそろわない限り現在の被害として示さない。

## 担当境界とデータ受け渡し

担当記号はIssueの記述にあるA/B/C/Dを使い、個人名やIssueにない合意内容は補わない。

| 担当 | 現在の責務・境界 | 主な受け渡し |
| --- | --- | --- |
| A | Web画面・操作・結果表示。APIとの通信、型検証、診断中の状態表示を担当。 | `web/src/types` の `Post`, `Clue`, `DiagnoseEvent`, `SessionResponse` と `web/src/lib/api.ts` を介してJSON/SSEを受け取る。Aの仮除外比較画面はIssue #69。 |
| B | 投稿単位の写真/本文から観測手がかりを抽出する担当範囲（Issue #60）。現行 `detect/` は抽出器・OCR/VLMクライアントを持つ。 | 入力は`Post`と画像bytes、出力は `PostExtraction(post_id, clues: Clue[])`。api pipelineが受け取りSSE `clues` と `conclusions.clues` へ渡す。独立 `POST /api/detect` の本番処理は未実装。 |
| C | 手がかりからの推理ルール、プロフィール推定・削除前後計算の担当範囲（Issue #59/#61/#65）。 | 入力は `Clue[]`、`Post[]`、プロフィール文、Gazetteer。`engine.infer` の試作Conclusionに加え、限定ルールで `residential_area` / `regular_station` / `employer_name` / `child_age` の ProfileItem を生成し根拠経路を返す。全プロフィール候補の推論や削除プランナーは未接続。 |
| D | API、Bluesky本人セッション/投稿取得、診断パイプライン、各担当間の統合（Issue #38/#40/#45/#48）。 | Cookie付きHTTPを受け、`Post[]`→Bの抽出→`Clue[]`→Cの推理→SSEイベントとしてAへ渡す。シミュレーションAPIはIssue #48の後続で、現行にはない。 |

**依存の流れ:** A ⇄ D(API/SSE) → B(抽出) → D(集約) → C(推理) → D(SSE) → A(表示)。型の共有元はPythonでは`common/`、TypeScriptでは`web/src/types/`。API固有のログイン要求/応答は `api/src/tkb_api/schemas.py` と `web/src/types/session.ts` で対応する。

## まだ実装されていない目標機能

- 全プロフィール項目に対する `found/weak/unknown`、確からしさ、根拠の網羅的な推論（現行は上記4項目の限定ルールと既存試作Conclusion）。
- 投稿の削除候補プランナー、選択投稿の仮除外・再推定API、実投稿の削除API。
- Blueskyログイン時以外の本番画像/本文抽出の統合完了確認。独立detectエンドポイントはモックのみで、本番は501。
- SSEの全体失敗イベント、途中切断後の再開・再送プロトコル。

これらはAGENTS.mdの目標やIssueの後続範囲であり、この文書の現行契約には含めない。
