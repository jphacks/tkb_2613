"""【使い捨ての実験】demo_observations.json に推理ルール（rules.py）を当てはめ、expected と比べる。

uv run python eval/spike/run.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rules import WEEKDAYS, Conclusion, Gazetteer, infer

from tkb_common.schemas import Clue, Post

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "demo_observations.json"


def _value_matches(attribute: str, expected: str, got: str) -> bool:
    if attribute == "routine":
        # 曜日と時刻がそろえば一致とみなす（言い回しは比べない）
        day = next((d for d in WEEKDAYS if f"{d}曜" in expected), None)
        hour = expected.split("の")[1].split("時")[0] if "時" in expected else None
        return bool(day and f"{day}曜" in got and (hour is None or f"{hour}時" in got))
    return expected == got


def main() -> None:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    clues = [Clue.model_validate(c) for c in doc["clues"]]
    posts = [Post.model_validate(p) for p in doc["posts"]]
    conclusions = infer(clues, posts, Gazetteer.load())

    print("## 結論と根拠")
    for c in conclusions:
        refs = ", ".join(f"{i}:{clues[i].type.value}「{clues[i].value}」" for i in c.clue_indices)
        print(f"- [{c.rule}] {c.attribute} = {c.value}")
        print(f"    根拠 {c.clue_indices}  {refs}")
        if c.note:
            print(f"    メモ {c.note}")

    print("\n## expected との比較")
    print("| attribute | expected | 結論 | 値 | 根拠：一致 | 足りない | 余分 |")
    print("|---|---|---|---|---|---|---|")
    for e in doc["expected"]:
        got: list[Conclusion] = [c for c in conclusions if c.attribute == e["attribute"]]
        if not got:
            missing = e["clue_indices"]
            print(f"| {e['attribute']} | {e['value']} | （ルールなし） | ❌ | | {missing} | |")
            continue
        best = max(got, key=lambda c: _value_matches(e["attribute"], e["value"], c.value))
        want, have = set(e["clue_indices"]), set(best.clue_indices)
        ok = "✅" if _value_matches(e["attribute"], e["value"], best.value) else "❌"
        print(
            f"| {e['attribute']} | {e['value']} | {best.value} | {ok} | "
            f"{sorted(want & have)} | {sorted(want - have)} | {sorted(have - want)} |"
        )
    others = [
        c for c in conclusions if c.attribute not in {e["attribute"] for e in doc["expected"]}
    ]
    for c in others:
        print(f"| {c.attribute} | （expected なし） | {c.value} | — | | | {c.clue_indices} |")


if __name__ == "__main__":
    main()
