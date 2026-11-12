import pytest

from tkb_common.corporate_name import normalize_corporate_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("株式会社青空商事", "青空商事"),
        ("青空商事株式会社", "青空商事"),
        ("(株)青空商事", "青空商事"),
        ("（株）青空商事", "青空商事"),
        ("㈱青空商事", "青空商事"),
        ("青空商事㈲", "青空商事"),
        ("ＡＯＺＯＲＡ　Ｔｒａｄｉｎｇ合同会社", "aozoratrading"),
        ("一般社団法人 青空協会", "青空協会"),
        ("医療法人社団青空会", "青空会"),
        ("特定非営利活動法人青空", "青空"),
        ("ヶ丘商店", "ケ丘商店"),
    ],
)
def test_normalize_corporate_name(raw: str, expected: str) -> None:
    assert normalize_corporate_name(raw) == expected


def test_the_legal_form_alone_is_not_a_name() -> None:
    assert normalize_corporate_name("株式会社") == ""
