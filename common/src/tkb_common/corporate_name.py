"""法人の名前の正規化。data-prep（法人番号の表を作る側）と engine（引く側）で同じものを使う。

法人番号公表サイトの商号と、投稿に書かれた名前を照らすために、表記の違いをそろえる。
- NFKC（全角・半角）、大文字・小文字、空白、「ヶ」と「ケ」
- 法人格の表記（株式会社、(株)、㈱、一般社団法人など）。名前の前と後ろのどちらにあっても取る
"""

import re
import unicodedata

# 長いものから順に取る（「医療法人社団」を「医療法人」より先に）
LEGAL_FORMS = (
    "特定非営利活動法人",
    "地方独立行政法人",
    "独立行政法人",
    "国立大学法人",
    "公立大学法人",
    "一般社団法人",
    "一般財団法人",
    "公益社団法人",
    "公益財団法人",
    "医療法人社団",
    "医療法人財団",
    "社会福祉法人",
    "医療法人",
    "学校法人",
    "宗教法人",
    "株式会社",
    "有限会社",
    "合同会社",
    "合資会社",
    "合名会社",
    "NPO法人",
)
# NFKC のあとの略記（㈱ は NFKC で「(株)」になる）
ABBREVIATIONS = ("(株)", "(有)", "(同)", "(資)", "(名)", "(社)", "(財)", "(医)", "(福)", "(学)")

_FORMS = sorted({f.casefold() for f in (*LEGAL_FORMS, *ABBREVIATIONS)}, key=len, reverse=True)
_FORM_RE = re.compile("|".join(re.escape(f) for f in _FORMS))


def normalize_corporate_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold().replace("ヶ", "ケ")
    text = re.sub(r"\s", "", text)
    return _FORM_RE.sub("", text)
