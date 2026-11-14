from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION, place_name_keys


def test_place_keys_cover_only_declared_surface_variants() -> None:
    keys = place_name_keys("　ﾄｳｷｮｳ ・文化　館 ")

    assert PLACE_INDEX_SCHEMA_VERSION >= 2
    assert "トウキョウ文化館" in keys
    assert "とうきょう文化館" in keys
    assert place_name_keys("東京文化館") != keys


def test_place_keys_keep_distinguishing_punctuation_and_long_vowel_mark() -> None:
    assert place_name_keys("コーヒー館") != place_name_keys("コヒ館")
    assert place_name_keys("A-B館") != place_name_keys("AB館")
