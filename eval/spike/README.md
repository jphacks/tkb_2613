# eval/spike（使い捨ての実験）

推理ルールを試すための実験コード。**engine の本実装ではない。main にはマージしない**（`spike/rules` ブランチだけに置く）。

- `rules.py`：R1（生活圏）・R2（行動時間）・R3（留守の時間）の試作。しきい値はファイルの先頭にある仮の値
- `run.py`：`eval/fixtures/demo_observations.json` に当てはめて、結論と根拠、expected との比較を表示する

```bash
uv run python eval/spike/run.py
```

`data/processed/` の stations・postal・muni_mesh を使う（`make data` で作る）。
