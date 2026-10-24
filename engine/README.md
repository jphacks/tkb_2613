# engine

手がかりの一覧から推理ルールで結論を出す部分（`tkb_engine`）。最小削除プランナーと再診断もここに置く。

- `rules.py`：推理ルール R1（生活圏）・R2（行動時間）・R3（留守の時間）と `infer`。入出力、しきい値の場所、ルールの足し方はファイル先頭の説明を参照
- `gazetteer.py`：data-prep の表（stations・postal・muni_mesh）を読み、駅名・郵便番号・住所を引き当てる

```python
from tkb_engine import Gazetteer, infer

conclusions = infer(clues, posts, Gazetteer.load())  # data/processed/ が要る（make data）
```

デモ用アカウントの手がかりに当てはめた結果は `eval/spike/run.py` で確かめる（`eval/spike/README.md`）。
