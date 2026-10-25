# engine

手がかりの一覧から推理ルールで結論を出す部分（`tkb_engine`）。最小削除プランナーと再診断もここに置く。

- `rules.py`：推理ルール R1（生活圏）・R2（行動時間）・R3（留守の時間）・R4（路線）・R5（名前）・R6（年齢）・R7（学校）と `infer`。入出力、しきい値の場所、ルールの足し方はファイル先頭の説明を参照
- `planner.py`：消したらどうなるか（`simulate`）と危ない投稿の選び方（`plan`）。モデルは呼ばず、手がかりから消す投稿の分を除いて `infer` をかけ直す。`plan` は最寄り駅・行動時間・留守の時間が崩れるまで、効き目の大きい投稿から最大3件を選ぶ
- `gazetteer.py`：data-prep の表（stations・postal・muni_mesh）を読み、駅名・郵便番号・住所を引き当てる

```python
from tkb_engine import Gazetteer, infer, plan, simulate

gaz = Gazetteer.load()  # data/processed/ が要る（make data）
conclusions = infer(clues, posts, gaz)
proposal = plan(clues, posts, gaz)  # proposal.delete / broken / before / after
what_if = simulate(clues, posts, gaz, ["at://..."])  # 選んだ投稿を消したとき
```

デモ用アカウントの手がかりに当てはめた結果は `eval/spike/run.py` で確かめる（`eval/spike/README.md`）。
