# API・SSE契約

Pythonの共有型は `common/src/tkb_common/schemas.py`、TypeScriptの受信型は `web/src/types/`。投稿や診断内容は保存しない。セッション本人のDIDで投稿とプロフィール文を取得する。

## 診断 SSE

形式は `event: <name>\ndata: <JSON>\n\n`。

| event | data | 意味 |
| --- | --- | --- |
| `post` | `{"post": Post}` | 読み込んだ本人投稿。`Post.images[].alt` も含む。 |
| `clues` | `{"post_id": string, "clues": Clue[], "error": string|null}` | 投稿本文、画像、altの観測結果。alt由来は `source:"alt"` と画像の `image_index` を持ち、矩形は持たない。 |
| `conclusions` | 下記 | 全投稿処理後に1回。 |
| `done` | `{"posts_seen": number}` | 正常完了。 |

`conclusions` のJSON:

```json
{
  "clues": [],
  "conclusions": [],
  "profile_claims": [
    {
      "attribute": "residential_area",
      "value": "文京区",
      "confidence": 0.65,
      "status": "weak",
      "evidence": [],
      "evidence_paths": [{"confidence":0.65,"evidence": [
        {"post_id":"at://…","clue_index":null,"required":true,"source":"post_text","image_index":null,"excerpt":"自宅近くの青葉商店街"},
        {"post_id":"at://…","clue_index":null,"required":true,"source":"post_text","image_index":null,"excerpt":"青葉商店街は文京区"}
      ]}],
      "assessment": {
        "minimal_scope":"bluesky", "offline_subtype":null,
        "psychological_resistance":null,"persona_context":null,
        "inference_ease":null,"inference_ease_basis":null,
        "harm_severity":null,"harm_scenario":null,"harm_prerequisites":[],"harm_status":"unknown"
      }
    }
  ],
  "owner_profile_text": "本人のプロフィール文",
  "self_report_clues": []
}
```

`profile_claims` の `confidence` は一致した文字列パターンに付ける暫定ルール値で、校正済み確率ではない。0.50未満は出さず、0.80未満は `weak`、0.80以上は `found` とする。根拠経路はAND条件、複数経路はOR条件。削除後は削除投稿を参照する経路を除いて再計算する。

`owner_profile_text` と `self_report_clues` は本人の自己申告として別枠で返す。限定的な横断経路でプロフィール文が根拠に使われる場合は `ProfileEvidence.source:"profile_text"` と具体的な抜粋を記録し、投稿本文や画像由来の根拠と区別する。プロフィール文を使う経路にも独立した2投稿の橋渡し根拠が要る。投稿本文の手がかりは `source:"text"`、画像alt由来は `source:"alt"`。

## 現行の限定ルール

- 居住エリア: 投稿またはプロフィール文に「自宅近くのX」、別投稿に「XはY」が明記され、Yと一致する本文 `place_text` 手がかりがある場合だけ候補にする。
- 雇用主: 投稿またはプロフィール文に「うちの会社のX」、別投稿に「YのX」が明記され、Yと一致する本文 `org_text` 手がかりがある場合だけ候補にする。
- プロフィール文をアンカーまたは値に使う経路でも、橋渡しと値を示す独立した2投稿を必須とする。プロフィール文は `profile_text` 証拠として保持し、投稿本文と区別する。
- 候補IDは `residential_area` と `employer_name`。一般名詞だけの橋渡し、型付き手がかりがない値、画像ロゴ・駅名標・訪問だけでは推定を作らない。異なる値が同じ橋渡しに結びつけば候補全体を出さない。
- 現段階では固有名を含む日本語の明示パターンだけを扱い、他の表現は推定しない。

## 失敗・プライバシー

投稿単位の抽出失敗は `clues.error` に載り、他の投稿の処理は継続する。Blueskyプロフィール取得・投稿取得・モデル初期化に失敗した場合はSSE開始前に通常のHTTPエラーを返す。リクエスト本文、プロフィール文、投稿内容、推定結果はログ・ディスクへ保存しない。
