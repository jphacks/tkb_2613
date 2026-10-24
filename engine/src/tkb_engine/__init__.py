"""手がかりの一覧から推理ルールで結論を出す。"""

from tkb_engine.gazetteer import Gazetteer
from tkb_engine.rules import Conclusion, infer, rule_r1, rule_r2, rule_r3

__all__ = ["Conclusion", "Gazetteer", "infer", "rule_r1", "rule_r2", "rule_r3"]
