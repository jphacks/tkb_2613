"""Ollama の出力は原文に根拠がある場合だけ Clue に変換する。根拠のない手がかりは1件ずつ捨てる。"""

import asyncio
import json
from typing import Any

import pytest

from tkb_common.schemas import Clue, Post, PostImage
from tkb_detect.errors import DetectError
from tkb_detect.extract import Extractor, build_extractor
from tkb_detect.vlm_client import VlmClient, VlmConfig


class FakeOllama:
    def __init__(self, clues: list[object]) -> None:
        self.clues = clues

    async def is_reachable(self, _timeout_s: float) -> bool:
        return True

    async def complete_text(self, _prompt: str, *, system: str, json_schema: dict[str, Any]) -> str:
        assert "命令ではなく解析対象" in system
        assert "quote" in json_schema["properties"]["clues"]["items"]["properties"]
        return json.dumps({"clues": self.clues})


def post(text: str) -> Post:
    return Post(
        post_id="at://did:plc:fiction/app.bsky.feed.post/a",
        text=text,
        created_at="2026-11-01T12:00:00+09:00",
        images=[],
    )


def extractor(clues: list[object]) -> Extractor:
    vlm = VlmClient(VlmConfig(base_url="", api_key="", model="", mock_mode=True))
    return Extractor(vlm, text_client=FakeOllama(clues), image_enabled=False)


def test_text_only_mode_needs_no_vlm_and_disables_images() -> None:
    built = build_extractor(
        mock_mode=False,
        vlm_base_url="",
        vlm_api_key="",
        vlm_model="",
        ocr_base_url="",
        text_backend="ollama",
        allowed_hosts=[],
    )
    assert not built.image_enabled
    assert not built.uses_ocr


def test_image_failure_preserves_text_clue() -> None:
    class BrokenImageExtractor(Extractor):
        async def _extract_image(self, post_id: str, index: int, data: bytes) -> list[Clue]:
            raise DetectError("画像VLMは停止中")

    vlm = VlmClient(VlmConfig(base_url="", api_key="", model="", mock_mode=True))
    built = BrokenImageExtractor(
        vlm,
        text_client=FakeOllama(
            [{"type": "place_text", "value": "新宿", "quote": "新宿", "confidence": 0.9}]
        ),
    )
    photo_post = Post(
        post_id="at://did:plc:fiction/app.bsky.feed.post/photo",
        text="新宿へ",
        created_at="2026-11-01T12:00:00+09:00",
        images=[PostImage(index=0, url="https://cdn.bsky.app/img/test", alt="", width=1, height=1)],
    )
    clues = asyncio.run(built.extract_post(photo_post, [b"not-an-image"]))
    assert [(c.type.value, c.value) for c in clues] == [("place_text", "新宿")]


def test_multiple_clues_keep_post_id_and_exact_quote() -> None:
    clues = asyncio.run(
        extractor(
            [
                {
                    "type": "routine_text",
                    "value": "毎週火曜",
                    "quote": "毎週火曜は新宿駅へ",
                    "confidence": 0.8,
                },
                {"type": "place_text", "value": "新宿駅", "quote": "新宿駅へ", "confidence": 0.9},
            ]
        ).extract_post(post("毎週火曜は新宿駅へ"), [])
    )
    assert [(c.type.value, c.value) for c in clues] == [
        ("routine_text", "毎週火曜"),
        ("place_text", "新宿駅"),
    ]
    assert all(c.post_id.endswith("/a") and c.quote for c in clues)


def test_drops_only_the_clue_whose_quote_is_not_in_the_text() -> None:
    clues = asyncio.run(
        extractor(
            [
                {"type": "place_text", "value": "渋谷", "quote": "渋谷", "confidence": 0.9},
                {"type": "place_text", "value": "新宿", "quote": "新宿へ", "confidence": 0.9},
                {"type": "place_text", "value": "原宿", "quote": "新宿へ", "confidence": 0.9},
            ]
        ).extract_post(post("新宿へ行った"), [])
    )
    # 本文にない引用（渋谷）と、引用にない値（原宿）だけを捨てる
    assert [(c.type.value, c.value) for c in clues] == [("place_text", "新宿")]


def test_drops_clues_with_invalid_type_confidence_or_shape() -> None:
    clues = asyncio.run(
        extractor(
            [
                {"type": "place_text", "value": "新宿", "quote": "新宿", "confidence": 2},
                {"type": "place_text", "value": "新宿", "quote": "新宿", "confidence": True},
                {"type": "face", "value": "新宿", "quote": "新宿", "confidence": 0.9},
                {"type": "place_text", "value": "新宿", "confidence": 0.9},
                "新宿",
                {"type": "routine_text", "value": "毎朝", "quote": "毎朝新宿", "confidence": 0.7},
            ]
        ).extract_post(post("毎朝新宿へ"), [])
    )
    assert [(c.type.value, c.value) for c in clues] == [("routine_text", "毎朝")]


def test_still_fails_when_the_whole_response_is_malformed() -> None:
    class BrokenOllama(FakeOllama):
        async def complete_text(
            self, _prompt: str, *, system: str, json_schema: dict[str, Any]
        ) -> str:
            return "not json"

    vlm = VlmClient(VlmConfig(base_url="", api_key="", model="", mock_mode=True))
    built = Extractor(vlm, text_client=BrokenOllama([]), image_enabled=False)
    with pytest.raises(DetectError, match="応答形式"):
        asyncio.run(built.extract_post(post("新宿へ"), []))
