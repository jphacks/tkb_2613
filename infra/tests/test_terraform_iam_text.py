"""IAM のロールとポリシーの description に、IAM が受け付けない文字を入れていないか確かめる。

IAM の description は Latin-1 の範囲（タブ・改行と 0x20〜0x7E・0xA1〜0xFF）だけを受け付け、
日本語を入れると terraform apply の途中で CreateRole が ValidationError になる
（2026-11-14 に起きた）。"""

import re
from pathlib import Path

TERRAFORM = Path(__file__).resolve().parents[1] / "terraform"
IAM_TYPES = ("aws_iam_role", "aws_iam_policy", "aws_iam_user")
ALLOWED = re.compile(r"^[\t\n\r\x20-\x7e\xa1-\xff]*$")
RESOURCE = re.compile(r'^resource "([a-z0-9_]+)" "([a-z0-9_]+)"')
DESCRIPTION = re.compile(r'^\s*description\s*=\s*"(.*)"\s*$')


def iam_descriptions() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for tf in sorted(TERRAFORM.glob("*.tf")):
        current: str | None = None
        for line in tf.read_text("utf-8").splitlines():
            if match := RESOURCE.match(line):
                current = f"{match[1]}.{match[2]}" if match[1] in IAM_TYPES else None
            elif current and (match := DESCRIPTION.match(line)):
                found.append((current, match[1]))
    return found


def test_iam_descriptions_use_only_characters_iam_accepts() -> None:
    found = iam_descriptions()
    assert found, "IAM の description が1つも見つからない（読み取りの正規表現を見直す）"
    bad = [name for name, text in found if not ALLOWED.match(text)]
    assert bad == [], f"IAM が受け付けない文字（日本語など）が description にある：{bad}"
