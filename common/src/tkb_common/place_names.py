"""Conservative, shared place-name keys for POI indexing and lookup."""

from __future__ import annotations

import unicodedata

# Bump this when key generation or the SQLite alias layout changes. Existing indexes
# with another PRAGMA user_version are intentionally ignored until regenerated.
PLACE_INDEX_SCHEMA_VERSION = 2
_MIDDLE_DOTS = frozenset({"・", "･", "·"})


def _base_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace() and character not in _MIDDLE_DOTS
    )


def _hiragana_key(value: str) -> str:
    # Katakana-to-hiragana script conversion only. It does not infer readings for
    # kanji or alter the underlying syllables; small kana and ー are preserved.
    return "".join(
        chr(ord(character) - 0x60) if "ァ" <= character <= "ヶ" else character
        for character in value
    )


def place_name_keys(value: str) -> tuple[str, ...]:
    """Return exact and script-variant keys without guessing kanji readings.

    NFKC handles width variants; whitespace and Japanese middle dots are ignored;
    katakana/hiragana variants share a key. Other punctuation and kanji are retained.
    Any key collision is returned as multiple candidates by the caller.
    """
    base = _base_key(value)
    if not base:
        return ()
    kana_folded = _hiragana_key(base)
    return tuple(dict.fromkeys((base, kana_folded)))
