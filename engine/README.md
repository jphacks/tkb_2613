# engine

手がかりの一覧から推理ルールで結論を出す部分（`tkb_engine`）。最小削除プランナーと再診断もここに置く。

- `rules.py`：推理ルール R1（生活圏）・R2（行動時間）・R3（留守の時間）・R4（市区町村）・R5（収集地区）・R6（区画）・R7（通学先）・R8（名前）・R9（年齢）・R10（仕事）・R11（路線）・R12（生年月日）と `infer`。入出力、しきい値の場所、ルールの足し方はファイル先頭の説明を参照
- `planner.py`：消したらどうなるか（`simulate`）と危ない投稿の選び方（`plan`）。モデルは呼ばず、手がかりから消す投稿の分を除いて `infer` をかけ直す。`plan` は名前・生年月日を優先し、住所の町域・区画・最寄り駅・行動時間・留守の時間も対象に最大3件を選ぶ
- `gazetteer.py`：data-prep の表（stations・postal・muni_mesh）を読み、駅名・郵便番号・住所を引き当てる

```python
from tkb_engine import Gazetteer, infer, plan, simulate

gaz = Gazetteer.load()  # data/processed/ が要る（make data）
conclusions = infer(clues, posts, gaz)
proposal = plan(clues, posts, gaz)  # proposal.delete / broken / before / after
what_if = simulate(clues, posts, gaz, ["at://..."])  # 選んだ投稿を消したとき
```

デモ用アカウントの手がかりに当てはめた結果は `eval/spike/run.py` で確かめる（`eval/spike/README.md`）。

## 拡張ルールの導入と確認

- `uv sync --all-packages --frozen` でバーコードの画像処理ライブラリもインストールする。
- `make data` で駅・郵便番号・市区町村メッシュ・学校の表を用意する。
  表がないときはそれに依存する推理を飛ばす。知識表だけで全ルールが動くわけではない。
- 知識表は `data-prep/manual/knowledge.json`。Dockerイメージにも同梱する。
- 推理は言語モデルを呼ばない。手がかりの抽出は従来どおりチームのモデルを使う。
- 投稿時刻を使うルールは3日以上に投稿が分散しているときだけ動く。同日に投稿したデモでは、
  本文と画像の手がかりだけを使い、投稿日を誕生日にしない。
- `infer` の名前の出力は `full_name` / `given_name_or_nickname`。生年月日は `birthday`。
  mainの身元カードと接続し、路線ルールはR11、生年月日はR12として残す。
- 削除提案と画面の「逃げ切り」は `full_name / given_name_or_nickname / birthday / home_area / home_block / station / active_time / routine` を対象にする。
  シミュレーションは実際の削除もモデル呼び出しも行わない。

知識表の指定袋価格は2025年1月31日の資料に基づく地域限定の候補照合であり、全国を網羅しない。
距離は市内の駅の平均位置による近似で、自宅からの正確な距離ではない。
八王子市の収集曜日と中央大学の時限は未確認のため空欄。未確認の時間割で大学を絞らない。
実際の学校データ取得と変換を含む確認、本番アカウントでの抽出精度の確認は別途必要。

`uv run pytest` は、手がかりの組み合わせ・削除前後・バーコード・APIの回帰を検証する。
`engine/tests/test_demo_fixtures.py` の駅などはfixture用の小さな表なので、
このテストの成功は本番データ整備や実写真の認識成功を保証しない。
