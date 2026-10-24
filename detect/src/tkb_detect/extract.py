"""投稿1件から手がかりを取り出す。

写真は1枚ずつ VLM に送り（OCR があれば OCR も使う）、本文は本文だけを VLM に送る。
モデルには観測だけを出させ、推理はさせない。写真と本文はメモリ上だけで扱い、ログに出さない。
画像のバイト列は呼び出し側（api）が cdn.bsky.app から取ってきて渡す。
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from tkb_common.schemas import Clue, ClueSource, ClueType, Post, Region
from tkb_detect.coords import COORDINATE_SPACE, CoordinateSpace, to_original_region
from tkb_detect.errors import DetectError
from tkb_detect.image import PreparedImage, prepare_image
from tkb_detect.ocr_client import OcrClient, OcrConfig
from tkb_detect.ocr_merge import merge_ocr
from tkb_detect.prompts import (
    PHOTO_SCHEMA,
    PHOTO_SYSTEM_PROMPT,
    PHOTO_USER_PROMPT,
    TEXT_SCHEMA,
    TEXT_SYSTEM_PROMPT,
    text_user_prompt,
)
from tkb_detect.vlm_client import VlmClient, VlmConfig

# 送った画像は JPEG に書き出し直している
SENT_MIME_TYPE = "image/jpeg"


class Extractor:
    def __init__(
        self,
        vlm: VlmClient,
        ocr: OcrClient | None = None,
        coordinate_space: CoordinateSpace | None = COORDINATE_SPACE,
    ) -> None:
        self._vlm = vlm
        self._ocr = ocr
        self._coordinate_space = coordinate_space

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        """投稿1件の手がかり。images は post.images と同じ順の画像のバイト列。"""
        if len(images) != len(post.images):
            raise DetectError("画像の数が投稿の写真の数と合いません")

        tasks = [self._extract_image(post.post_id, i, data) for i, data in enumerate(images)]
        if post.text.strip():
            tasks.append(self._extract_text(post.post_id, post.text))

        results = await asyncio.gather(*tasks)
        return _dedupe([clue for clues in results for clue in clues])

    async def _extract_image(self, post_id: str, index: int, data: bytes) -> list[Clue]:
        prepared = prepare_image(data)
        vlm_task = self._vlm.complete(
            prepared.jpeg,
            SENT_MIME_TYPE,
            PHOTO_USER_PROMPT,
            system=PHOTO_SYSTEM_PROMPT,
            json_schema=PHOTO_SCHEMA,
        )
        if self._ocr is None:
            raw = await vlm_task
            return self._photo_clues(post_id, index, raw, prepared)

        # OCR は元の画像を読み、元の画像のピクセルで箱を返す
        raw, lines = await asyncio.gather(vlm_task, self._ocr.recognize(data))
        return merge_ocr(post_id, index, self._photo_clues(post_id, index, raw, prepared), lines)

    def _photo_clues(
        self, post_id: str, index: int, raw: str, prepared: PreparedImage
    ) -> list[Clue]:
        clues = []
        for item in _parse_items(raw):
            box = item.get("bbox_2d")
            clue = _build_clue(
                item,
                post_id=post_id,
                image_index=index,
                region_box=box if isinstance(box, list) else None,
                source=ClueSource.VLM,
                to_region=lambda b: to_original_region(
                    b, self._require_space(), prepared.sent, prepared.original
                ),
            )
            if clue is not None:
                clues.append(clue)
        return clues

    async def _extract_text(self, post_id: str, text: str) -> list[Clue]:
        raw = await self._vlm.complete_text(
            text_user_prompt(text), system=TEXT_SYSTEM_PROMPT, json_schema=TEXT_SCHEMA
        )
        clues = []
        for item in _parse_items(raw):
            clue = _build_clue(
                item,
                post_id=post_id,
                image_index=None,
                region_box=None,
                source=ClueSource.TEXT,
                to_region=lambda _b: None,
            )
            if clue is not None:
                clues.append(clue)
        return clues

    def _require_space(self) -> CoordinateSpace:
        if self._coordinate_space is None:
            raise DetectError("VLM の座標の単位がまだ決まっていません（coords.COORDINATE_SPACE）")
        return self._coordinate_space


def build_extractor(
    *,
    mock_mode: bool,
    vlm_base_url: str,
    vlm_api_key: str,
    vlm_model: str,
    ocr_base_url: str,
) -> Extractor:
    """設定から作る。OCR は OCR_BASE_URL が空なら使わない。"""
    vlm = VlmClient(
        VlmConfig(base_url=vlm_base_url, api_key=vlm_api_key, model=vlm_model, mock_mode=mock_mode)
    )
    use_ocr = bool(ocr_base_url.strip()) and not mock_mode
    ocr = OcrClient(OcrConfig(base_url=ocr_base_url, mock_mode=False)) if use_ocr else None
    return Extractor(vlm, ocr)


def _parse_items(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except ValueError as e:
        # 応答の中身はログや例外に出さない
        raise DetectError("VLM の応答が JSON ではありません") from e
    items = data.get("clues") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise DetectError("VLM の応答に clues がありません")
    return [item for item in items if isinstance(item, dict)]


def _build_clue(
    item: dict[str, Any],
    *,
    post_id: str,
    image_index: int | None,
    region_box: list[Any] | None,
    source: ClueSource,
    to_region: Callable[[list[float]], Region | None],
) -> Clue | None:
    """VLM の1件を手がかりにする。形が合わないものは捨てる。"""
    clue_type = item.get("type")
    value = item.get("value")
    confidence = item.get("confidence")
    if not isinstance(clue_type, str):
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        return None

    region = None
    if region_box is not None and all(isinstance(n, int | float) for n in region_box):
        region = to_region([float(n) for n in region_box])

    try:
        return Clue(
            post_id=post_id,
            image_index=image_index,
            type=ClueType(clue_type),
            value=value.strip(),
            region=region,
            confidence=min(max(float(confidence), 0.0), 1.0),
            source=source,
        )
    except (ValueError, ValidationError):
        return None


def _dedupe(clues: list[Clue]) -> list[Clue]:
    seen: set[tuple[int | None, ClueType, str]] = set()
    unique = []
    for clue in clues:
        key = (clue.image_index, clue.type, clue.value)
        if key not in seen:
            seen.add(key)
            unique.append(clue)
    return unique
