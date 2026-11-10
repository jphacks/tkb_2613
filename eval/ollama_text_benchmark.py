"""架空投稿の固定正解で Ollama 本文抽出を比較。本文・出力は表示しない。"""

import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

import httpx

from tkb_common.schemas import Post
from tkb_detect.extract import build_extractor
from tkb_detect.guard import ensure_team_endpoint
from tkb_detect.ollama_client import OllamaClient, OllamaConfig

FIXTURE = Path(__file__).parent / "fixtures/ollama_text_gold.json"
MODELS = ("qwen3:1.7b", "qwen3:4b-instruct")


class RecordingClient:
    def __init__(self, inner: OllamaClient) -> None:
        self.inner = inner
        self.raw: str | None = None

    async def is_reachable(self, timeout_s: float) -> bool:
        return await self.inner.is_reachable(timeout_s)

    async def complete_text(self, prompt: str, *, system: str, json_schema: dict[str, Any]) -> str:
        self.raw = await self.inner.complete_text(prompt, system=system, json_schema=json_schema)
        return self.raw


async def run() -> None:
    items = json.loads(FIXTURE.read_text())
    base_url = ensure_team_endpoint(os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"), [])
    for model in MODELS:
        extractor = build_extractor(
            mock_mode=False,
            vlm_base_url="",
            vlm_api_key="",
            vlm_model="",
            ocr_base_url="",
            text_backend="ollama",
            ollama_base_url=base_url,
            ollama_model=model,
            allowed_hosts=[],
        )
        recorder = RecordingClient(OllamaClient(OllamaConfig(base_url, model, ())))
        extractor._text_client = recorder  # 比較中だけ応答をメモリで観察し、内容は表示しない
        correct = missed = false = accepted = json_syntax = 0
        durations: list[float] = []
        for index, item in enumerate(items):
            post = Post(
                post_id=f"at://did:plc:fiction/app.bsky.feed.post/{index}",
                text=item["text"],
                created_at="2026-11-01T12:00:00+09:00",
                images=[],
            )
            started = time.monotonic()
            recorder.raw = None
            try:
                clues = await extractor.extract_post(post, [])
                accepted += 1
                actual = {(c.type.value, c.value) for c in clues}
            except Exception:
                actual = set()
            if recorder.raw is not None:
                try:
                    json.loads(recorder.raw)
                    json_syntax += 1
                except ValueError:
                    pass
            durations.append(time.monotonic() - started)
            gold = {(t, v) for t, v in item["gold"]}
            correct += len(actual & gold)
            missed += len(gold - actual)
            false += len(actual - gold)
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            loaded = (await client.get(f"{base_url}/api/ps")).json().get("models", [])
        resident = next(
            (m.get("size", 0) - m.get("size_vram", 0) for m in loaded if m.get("name") == model), 0
        )
        print(
            json.dumps(
                {
                    "model": model,
                    "posts": len(items),
                    "correct": correct,
                    "missed": missed,
                    "false": false,
                    "json_syntax": json_syntax,
                    "accepted": accepted,
                    "mean_seconds": round(statistics.mean(durations), 2),
                    "median_seconds": round(statistics.median(durations), 2),
                    "ollama_cpu_resident_gib": round(resident / 2**30, 2),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(run())
