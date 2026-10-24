"""OCR の結果を VLM の手がかりと合わせる。

- VLM の手がかりの文字が OCR の行に含まれていれば、位置は OCR の箱（元の画像のピクセル）を使う
- OCR の行から郵便番号と電話番号を正規表現で拾い、VLM が出していなければ足す
"""

import re
import unicodedata

from tkb_common.schemas import Clue, ClueSource, ClueType, Region
from tkb_detect.ocr_client import OcrLine

POSTAL_RE = re.compile(r"(?<!\d)(\d{3})-?(\d{4})(?!\d)")
PHONE_RE = re.compile(r"(?<!\d)(0\d{1,4})-(\d{1,4})-(\d{3,4})(?!\d)")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[‐-‒–—―ーｰ−]", "-", text)
    return re.sub(r"\s+", "", text)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _has_area(box: Region) -> bool:
    return box[2] > box[0] and box[3] > box[1] and min(box) >= 0


def _overlaps(a: Region, b: Region) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _matching_box(clue: Clue, lines: list[OcrLine]) -> Region | None:
    value = _normalize(clue.value)
    if len(value) < 2:
        return None
    for line in lines:
        if not _has_area(line.box):
            continue
        text = _normalize(line.text)
        if value not in text and text not in value:
            continue
        if clue.region is None or _overlaps(clue.region, line.box):
            return line.box
    return None


def _regex_clues(post_id: str, image_index: int, lines: list[OcrLine]) -> list[Clue]:
    clues: list[Clue] = []
    for line in lines:
        text = _normalize(line.text)
        # 電話番号を先に拾い、その一部（047-000-0000 の 000-0000 など）を郵便番号にしない
        phones = list(PHONE_RE.finditer(text))
        found: list[tuple[ClueType, str]] = [
            (ClueType.POSTAL_CODE, f"{m[1]}-{m[2]}")
            for m in POSTAL_RE.finditer(text)
            if not any(m.start() < p.end() and p.start() < m.end() for p in phones)
        ]
        found += [(ClueType.PHONE, "-".join(m.groups())) for m in phones]
        if not _has_area(line.box):
            continue
        for clue_type, value in found:
            clues.append(
                Clue(
                    post_id=post_id,
                    image_index=image_index,
                    type=clue_type,
                    value=value,
                    region=line.box,
                    confidence=min(max(line.score, 0.0), 1.0),
                    source=ClueSource.OCR,
                )
            )
    return clues


def merge_ocr(
    post_id: str, image_index: int, vlm_clues: list[Clue], lines: list[OcrLine]
) -> list[Clue]:
    merged = []
    for clue in vlm_clues:
        box = _matching_box(clue, lines)
        merged.append(clue if box is None else clue.model_copy(update={"region": box}))

    taken = {(c.type, _digits(c.value)) for c in merged}
    for clue in _regex_clues(post_id, image_index, lines):
        key = (clue.type, _digits(clue.value))
        if key not in taken:
            taken.add(key)
            merged.append(clue)
    return merged
