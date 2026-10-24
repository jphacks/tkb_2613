# eval/spike（推理ルールの検証の記録）

推理ルール R1〜R3 を `eval/fixtures/demo_observations.json` に当てはめて確かめた記録。ルールの本体は `engine/src/tkb_engine/rules.py`。

- `run.py`：fixture に `tkb_engine.infer` を当てはめて、結論と根拠、expected との比較を表示する

```bash
uv run python eval/spike/run.py
```

`data/processed/` の stations・postal・muni_mesh を使う（`make data` で作る）。

## 結果（2026-10-24）

| attribute | expected | 結論 | 値 | 根拠：一致 | 足りない | 余分 |
|---|---|---|---|---|---|---|
| station | 根津駅 | 根津駅 | ✅ | [1, 15, 16] | [3, 6, 13] | [] |
| occupation | 夜勤のある現場仕事 | （ルールなし） | ❌ | | [2, 7, 9] | |
| name | はるき（25歳、誕生日は10月17日ごろ） | （ルールなし） | ❌ | | [10, 11, 17] | |
| routine | 毎週火曜の20時ごろにジム | 毎週火曜 20時ごろに出かけている（ジム・毎週火曜のジム） | ✅ | [5, 8, 14] | [] | [] |
| home_area | （expected なし） | 弥生 | — | | | [15, 16] |
| active_time | （expected なし） | 平日 8時ごろに根津駅のまわりにいる | — | | | [1, 6] |

- station と routine は値が一致した。station の根拠には、平日朝の「電車混んでる」（3・13）と駅の近くの赤札堂（6）がまだ入っていない
- occupation と name はルールがまだない
