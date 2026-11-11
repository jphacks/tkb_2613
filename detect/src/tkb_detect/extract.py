"""投稿1件から手がかりを取り出す。

写真は1枚ずつ VLM に送り（OCR があれば OCR も使う）、本文は本文だけを VLM に送る。
モデルには観測だけを出させ、推理はさせない。写真と本文はメモリ上だけで扱い、ログに出さない。
画像のバイト列は呼び出し側（api）が cdn.bsky.app から取ってきて渡す。
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from pydantic import ValidationError

from tkb_common.name_text import is_person_name_text
from tkb_common.schemas import Clue, ClueSource, ClueType, Post, Region
from tkb_detect.barcode import read_codes
from tkb_detect.coords import COORDINATE_SPACE, CoordinateSpace, to_original_region
from tkb_detect.errors import DetectError, OutputCutOffError
from tkb_detect.image import PreparedImage, crop_and_enlarge, prepare_image
from tkb_detect.ocr_client import OcrClient, OcrConfig
from tkb_detect.ocr_merge import merge_ocr
from tkb_detect.ollama_client import OllamaClient, OllamaConfig
from tkb_detect.prompts import (
    OLLAMA_TEXT_PROMPT,
    OLLAMA_TEXT_SCHEMA,
    PHOTO_SCHEMA,
    PHOTO_SYSTEM_PROMPT,
    PHOTO_USER_PROMPT,
    TEXT_CLUE_TYPES,
    TEXT_SCHEMA,
    TEXT_SYSTEM_PROMPT,
    ZOOM_SCHEMA,
    ZOOM_USER_PROMPT,
    text_user_prompt,
)
from tkb_detect.vlm_client import VlmClient, VlmConfig

# 小さく写ったものは読み間違えやすいのに、モデルは confidence を下げない
# （テスト写真で、24×97 ピクセルの看板を読み間違えたまま 0.9 を付けた）。
# 枠の短い辺が元の画像で SMALL_REGION_MIN_SIDE_PX より小さければ、confidence を
# SMALL_REGION_MAX_CONFIDENCE までにする。拡大して読み直し、2回とも同じに読めたものは除く
from tkb_detect.zoom import (
    SMALL_REGION_MAX_CONFIDENCE,
    SMALL_REGION_MIN_SIDE_PX,
    cap_small_region,
    clean_value,
    resolve_zoom,
    select_zoom_targets,
)

logger = logging.getLogger(__name__)


async def _timed[T](stage: str, operation: Awaitable[T]) -> T:
    """並列の呼び出しごとの待ち時間。投稿の内容や ID は記録しない。"""
    started = time.monotonic()
    try:
        return await operation
    finally:
        logger.info("診断の内訳：%s %.2f 秒", stage, time.monotonic() - started)


__all__ = [
    "SMALL_REGION_MAX_CONFIDENCE",
    "SMALL_REGION_MIN_SIDE_PX",
    "Extractor",
    "build_extractor",
]

# 送った画像は JPEG に書き出し直している
SENT_MIME_TYPE = "image/jpeg"
# 出力の上限。qwen3.6-27b（RunPod）は約30トークン/秒なので、1回の呼び出しが
# 待ち時間の60秒（中継が切れる100秒）に収まるようにする。ふだんの出力は写真で約350、本文で約100
PHOTO_MAX_TOKENS = 1024
TEXT_MAX_TOKENS = 512
# json_schema で縛っても JSON の中の空白は何個でも許されるため、qwen3.6-27b が空白と改行を
# 出し続けて止まらないことがある（vLLM 0.32 では whitespace_pattern などの指定が効かなかった）。
# 繰り返しのペナルティで止まるが、JSON のキーの繰り返しにも効いて手がかりを取りこぼすので、
# 出力が上限で切れたときのやり直しにだけ使う
RETRY_REPETITION_PENALTY = 1.05
# 拡大して読み直すときの出力の上限（ふだんは数件だけ）
ZOOM_MAX_TOKENS = 256


class TextClient(Protocol):
    async def is_reachable(self, timeout_s: float) -> bool: ...

    async def complete_text(
        self, prompt: str, *, system: str, json_schema: dict[str, Any]
    ) -> str: ...


class Extractor:
    def __init__(
        self,
        vlm: VlmClient,
        ocr: OcrClient | None = None,
        coordinate_space: CoordinateSpace | None = COORDINATE_SPACE,
        zoom: bool = True,
        text_client: TextClient | None = None,
        image_enabled: bool = True,
        station_names: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self._vlm = vlm
        self._ocr = ocr
        self._coordinate_space = coordinate_space
        self._zoom = zoom
        self._text_client = text_client
        self.image_enabled = image_enabled
        self._station_names = frozenset(station_names)

    @property
    def uses_ocr(self) -> bool:
        return self._ocr is not None

    async def model_reachable(self, timeout_s: float) -> bool:
        """モデルと OCR のサーバーが応答するか（診断を始める前の確認）。

        モデルは画像を読むモデル。Ollama のときは本文のモデル。

        OCR を使う設定で OCR だけ落ちていると、写真の投稿がすべて失敗したまま1回と数えられるので、
        写真も読むときは OCR も確かめる。
        """
        if self._text_client is not None:
            model_task = self._text_client.is_reachable(timeout_s)
        else:
            model_task = self._vlm.is_reachable(timeout_s)
        if self._ocr is None or not self.image_enabled:
            return await model_task
        model_ok, ocr_ok = await asyncio.gather(model_task, self._ocr.is_reachable(timeout_s))
        return model_ok and ocr_ok

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        """投稿1件の手がかり。images は post.images と同じ順の画像のバイト列。"""
        if self.image_enabled and len(images) != len(post.images):
            raise DetectError("画像の数が投稿の写真の数と合いません")

        tasks = (
            [self._extract_image(post.post_id, i, data) for i, data in enumerate(images)]
            if self.image_enabled
            else []
        )
        if post.text.strip():
            tasks.append(self._extract_text(post.post_id, post.text))
        tasks.extend(
            self._extract_text(
                post.post_id, image.alt, image_index=image.index, source=ClueSource.ALT
            )
            for image in post.images
            if image.alt.strip()
        )

        if self._text_client is not None and self.image_enabled:
            # 画像VLMの停止時も、本文から得た手がかりは残す。
            settled = await asyncio.gather(*tasks, return_exceptions=True)
            results = [r for r in settled if isinstance(r, list)]
            if not results and settled:
                raise DetectError("手がかりを取り出せませんでした")
        else:
            results = await asyncio.gather(*tasks)
        return _dedupe(
            [
                clue
                for clues in results
                for clue in clues
                if clue.type is not ClueType.NAME_TEXT or is_person_name_text(clue.value)
            ]
        )

    async def extract_profile_text(self, did: str, text: str) -> list[Clue]:
        """Analyze the authenticated owner's profile description as self-report only."""
        if not text.strip():
            return []
        return await self._extract_text(f"profile:{did}", text, source=ClueSource.PROFILE_TEXT)

    async def _extract_image(self, post_id: str, index: int, data: bytes) -> list[Clue]:
        codes_task = asyncio.create_task(
            asyncio.to_thread(_read_codes_safely, data, post_id, index)
        )
        clues = await self._extract_image_with_models(post_id, index, data)
        codes = await codes_task
        if not codes:
            return clues
        return [*codes, *(c for c in clues if c.type is not ClueType.CODE)]

    async def _extract_image_with_models(self, post_id: str, index: int, data: bytes) -> list[Clue]:
        prepare_started = time.monotonic()
        try:
            # 画像の縮小・変換は CPU を使うので、別のスレッドで行う
            # （ほかの人の応答と keep-alive を止めない）
            prepared = await asyncio.to_thread(prepare_image, data)
        finally:
            logger.info("診断の内訳：画像準備 %.2f 秒", time.monotonic() - prepare_started)
        vlm_task = _timed(
            "写真VLM",
            _retry_if_cut_off(
                lambda penalty: self._vlm.complete(
                    prepared.jpeg,
                    SENT_MIME_TYPE,
                    PHOTO_USER_PROMPT,
                    system=PHOTO_SYSTEM_PROMPT,
                    json_schema=PHOTO_SCHEMA,
                    max_tokens=PHOTO_MAX_TOKENS,
                    repetition_penalty=penalty,
                )
            ),
        )
        if self._ocr is None:
            raw = await vlm_task
            return await self._reread_small(data, self._photo_clues(post_id, index, raw, prepared))

        # OCR は元の画像を読み、元の画像のピクセルで箱を返す
        raw, lines = await asyncio.gather(vlm_task, _timed("OCR", self._ocr.recognize(data)))
        clues = await self._reread_small(data, self._photo_clues(post_id, index, raw, prepared))
        return merge_ocr(post_id, index, clues, lines, station_names=self._station_names)

    async def _reread_small(self, data: bytes, clues: list[Clue]) -> list[Clue]:
        """小さい文字や映り込みを拡大して読み直し、小ささによる confidence の上限をかける。"""
        targets = select_zoom_targets(clues) if self._zoom else []
        if not targets:
            return [cap_small_region(c) for c in clues]

        resolved = await asyncio.gather(*(self._zoom_into(data, t) for t in targets))
        replacements = {id(t): r for t, r in zip(targets, resolved, strict=True)}
        final: list[Clue] = []
        for clue in clues:
            final.extend(replacements.get(id(clue), [cap_small_region(clue)]))
        return final

    async def _zoom_into(self, data: bytes, target: Clue) -> list[Clue]:
        region = target.region
        if region is None:  # select_zoom_targets は region のあるものだけを選ぶ
            return [target]
        try:
            # 切り出しと拡大は CPU を使うので別のスレッドで1回だけ行い、再試行では同じ画像を送る
            cropped = await asyncio.to_thread(crop_and_enlarge, data, region)
            raw = await _timed(
                "拡大VLM",
                _retry_if_cut_off(
                    lambda penalty: self._vlm.complete(
                        cropped,
                        SENT_MIME_TYPE,
                        ZOOM_USER_PROMPT,
                        system=PHOTO_SYSTEM_PROMPT,
                        json_schema=ZOOM_SCHEMA,
                        max_tokens=ZOOM_MAX_TOKENS,
                        repetition_penalty=penalty,
                    )
                ),
            )
            items = _parse_items(raw)
        except DetectError:
            # 読み直しに失敗しても、1回目の読みは残す（強くは信じない）
            return [cap_small_region(target)]
        return resolve_zoom(target, items)

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

    async def _extract_text(
        self,
        post_id: str,
        text: str,
        *,
        image_index: int | None = None,
        source: ClueSource = ClueSource.TEXT,
    ) -> list[Clue]:
        if self._text_client is not None:
            return await self._extract_ollama_text(post_id, text, image_index, source)
        raw = await _timed(
            "本文VLM",
            _retry_if_cut_off(
                lambda penalty: self._vlm.complete_text(
                    text_user_prompt(text),
                    system=TEXT_SYSTEM_PROMPT,
                    json_schema=TEXT_SCHEMA,
                    max_tokens=TEXT_MAX_TOKENS,
                    repetition_penalty=penalty,
                )
            ),
        )
        clues = []
        for item in _parse_items(raw):
            clue = _build_clue(
                item,
                post_id=post_id,
                image_index=image_index,
                region_box=None,
                source=source,
                to_region=lambda _b: None,
            )
            if clue is not None:
                clues.append(clue)
        return clues

    async def _extract_ollama_text(
        self,
        post_id: str,
        text: str,
        image_index: int | None = None,
        source: ClueSource = ClueSource.TEXT,
    ) -> list[Clue]:
        if self._text_client is None:
            raise DetectError("Ollama の設定がありません")
        raw = await _timed(
            "本文Ollama",
            self._text_client.complete_text(
                text_user_prompt(text), system=OLLAMA_TEXT_PROMPT, json_schema=OLLAMA_TEXT_SCHEMA
            ),
        )
        try:
            data = json.loads(raw)
            items = data["clues"]
            if not isinstance(items, list):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise DetectError("Ollama の応答形式が不正です") from None
        clues: list[Clue] = []
        for item in items:
            clue = _ollama_clue(item, text, post_id, image_index, source)
            if clue is not None:
                clues.append(clue)
        if len(clues) < len(items):
            # 本文に根拠がない・形が違う手がかりだけを捨て、残りは使う（件数だけを出す）
            logger.info("本文Ollama：%d 件の手がかりを捨てました", len(items) - len(clues))
        return _dedupe(clues)

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
    coordinate_space: CoordinateSpace | None = COORDINATE_SPACE,
    zoom: bool = True,
    allowed_hosts: Sequence[str] | None = None,
    text_backend: str = "vlm",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "qwen3:4b-instruct",
    station_names: set[str] | frozenset[str] = frozenset(),
) -> Extractor:
    """設定から作る。OCR は OCR_BASE_URL が空なら使わない。

    allowed_hosts は VLM と OCR の送り先の許可リスト。None なら環境変数
    MODEL_ALLOWED_HOST_SUFFIXES を読む（guard.py）。
    """
    hosts = tuple(allowed_hosts) if allowed_hosts is not None else None
    if text_backend not in {"vlm", "ollama"}:
        raise DetectError("本文のモデル設定が不正です")
    image_enabled = bool(vlm_base_url.strip()) or text_backend == "vlm"
    vlm = VlmClient(
        VlmConfig(
            base_url=vlm_base_url,
            api_key=vlm_api_key,
            model=vlm_model,
            mock_mode=mock_mode or not image_enabled,
            allowed_hosts=hosts,
        )
    )
    use_ocr = image_enabled and bool(ocr_base_url.strip()) and not mock_mode
    ocr = (
        OcrClient(OcrConfig(base_url=ocr_base_url, mock_mode=False, allowed_hosts=hosts))
        if use_ocr
        else None
    )
    text_client = (
        OllamaClient(OllamaConfig(ollama_base_url, ollama_model, hosts))
        if text_backend == "ollama" and not mock_mode
        else None
    )
    return Extractor(
        vlm,
        ocr if image_enabled else None,
        coordinate_space,
        zoom,
        text_client=text_client,
        image_enabled=image_enabled,
        station_names=station_names,
    )


def _read_codes_safely(data: bytes, post_id: str, index: int) -> list[Clue]:
    """バーコードの読み取りに失敗しても、言語モデルの手がかりは残す。"""
    try:
        return read_codes(data, post_id, index)
    except (OSError, ValueError):
        return []


async def _retry_if_cut_off(call: Callable[[float | None], Awaitable[str]]) -> str:
    """出力が上限で切れたら（空白が止まらなかったら）、繰り返しのペナルティを付けて1回だけやり直す。"""
    try:
        return await call(None)
    except OutputCutOffError:
        logger.info("診断の内訳：VLM出力上限による再試行 1 件")
        return await call(RETRY_REPETITION_PENALTY)


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
    if clue_type == ClueType.NAME_TEXT.value and not is_person_name_text(value):
        return None

    region = None
    if region_box is not None and all(isinstance(n, int | float) for n in region_box):
        region = to_region([float(n) for n in region_box])

    try:
        return Clue(
            post_id=post_id,
            image_index=image_index,
            type=ClueType(clue_type),
            value=clean_value(value),
            region=region,
            confidence=min(max(float(confidence), 0.0), 1.0),
            source=source,
        )
    except (ValueError, ValidationError):
        return None


def _ollama_clue(
    item: object,
    text: str,
    post_id: str,
    image_index: int | None,
    source: ClueSource,
) -> Clue | None:
    """Ollama の手がかり1件を Clue にする。引用が本文になく値が引用にない、形・確信度・型が
    違うものは None（その1件だけを捨てる。モデルの作り話や本文中の指示に引きずられた値を使わない）。
    """
    if not isinstance(item, dict) or set(item) != {"type", "value", "quote", "confidence"}:
        return None
    quote, value, confidence = item["quote"], item["value"], item["confidence"]
    if not (
        isinstance(quote, str)
        and isinstance(value, str)
        and quote
        and value
        and quote in text
        and value in quote
    ):
        return None
    if (
        not isinstance(confidence, int | float)
        or isinstance(confidence, bool)
        or not 0 <= confidence <= 1
    ):
        return None
    clue = _build_clue(
        item,
        post_id=post_id,
        image_index=image_index,
        region_box=None,
        source=source,
        to_region=lambda _b: None,
    )
    if clue is None or clue.type not in TEXT_CLUE_TYPES:
        return None
    return clue.model_copy(update={"quote": quote})


def _dedupe(clues: list[Clue]) -> list[Clue]:
    seen: set[tuple[int | None, ClueType, str, ClueSource | None]] = set()
    unique = []
    for clue in clues:
        # Preserve an OCR station-sign clue alongside an identical VLM clue. The
        # regular-station rule is deliberately gated on OCR evidence.
        source = clue.source if clue.type is ClueType.STATION_SIGN else None
        key = (clue.image_index, clue.type, clue.value, source)
        if key not in seen:
            seen.add(key)
            unique.append(clue)
    return unique
