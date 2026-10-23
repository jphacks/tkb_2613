from tkb_data_prep.area_text import (
    Item,
    Qualified,
    Scope,
    parse_items,
    parse_qualified,
    split_top,
)


def test_split_top_ignores_separators_inside_parentheses() -> None:
    text = "児玉郡（神川町（上阿久原及び渡瀬を除く。）、上里町）、本庄市"

    assert split_top(text, ("、",)) == [
        "児玉郡（神川町（上阿久原及び渡瀬を除く。）、上里町）",
        "本庄市",
    ]


def test_parse_items_carries_prefecture_forward() -> None:
    text = "東京都町田市（三輪町を除く。）、八王子市、神奈川県相模原市緑区（小原及び吉野に限る。）"

    assert parse_items(text) == [
        Item("東京都", "町田市", "三輪町を除く"),
        Item("東京都", "八王子市", ""),
        Item("神奈川県", "相模原市緑区", "小原及び吉野に限る"),
    ]


def test_parse_items_handles_other_prefectures() -> None:
    items = parse_items("群馬県高崎市新町、多野郡、埼玉県熊谷市妻沼小島")

    assert [(i.pref, i.name) for i in items] == [
        ("群馬県", "高崎市新町"),
        ("群馬県", "多野郡"),
        ("埼玉県", "熊谷市妻沼小島"),
    ]


def test_parse_qualified_lists_names_with_their_own_qualifiers() -> None:
    qualified = parse_qualified("神川町（上阿久原及び渡瀬を除く。）、上里町及び美里町に限る")

    assert qualified == Qualified(
        Scope.LIMIT,
        (("神川町", "上阿久原及び渡瀬を除く"), ("上里町", ""), ("美里町", "")),
    )


def test_parse_qualified_reads_exclusions_and_rejects_other_text() -> None:
    assert parse_qualified("東秩父村を除く") == Qualified(Scope.EXCLUDE, (("東秩父村", ""),))
    assert parse_qualified("宝水町") is None
