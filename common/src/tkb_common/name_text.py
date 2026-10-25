"""観測された文字を人物名として扱ってよいかの最低限の確認。"""

import re
import unicodedata

CELEBRATION_TEXT = re.compile(
    r"\b(?:happy|birthday|hbd|party|congratulations|congrats)\b|誕生日|おめでとう|記念日",
    re.IGNORECASE,
)


def is_person_name_text(value: str) -> bool:
    """数字や誕生日の飾り文字を名前として推理に使わない。"""
    text = unicodedata.normalize("NFKC", value).strip()
    text = CELEBRATION_TEXT.sub("", text).strip(" 「」『』:：!！")
    if not text or text[0].isdigit():
        return False
    return any(char.isalpha() and char.lower() != "x" for char in text)
