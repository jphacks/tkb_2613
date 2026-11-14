"""ローカル Ollama の本文専用クライアント。投稿や応答をログに残さない。"""

from dataclasses import dataclass
from typing import Any

import httpx

from tkb_detect.errors import DetectError
from tkb_detect.guard import ensure_team_endpoint


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = "qwen3:4b-instruct"
    allowed_hosts: tuple[str, ...] | None = None
    # 応答の待ち時間は制限しない（CPU 実行で遅くても止めない）。つながらないときだけ早めに諦める
    timeout_s: float | None = None


class OllamaClient:
    def __init__(self, config: OllamaConfig) -> None:
        self._base_url = ensure_team_endpoint(config.base_url, config.allowed_hosts)
        self._model = config.model
        self._timeout = config.timeout_s

    async def is_reachable(self, timeout_s: float) -> bool:
        try:
            async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                response.raise_for_status()
                return any(m.get("name") == self._model for m in response.json().get("models", []))
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return False

    async def complete_text(self, prompt: str, *, system: str, json_schema: dict[str, Any]) -> str:
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "format": json_schema,
            "options": {"temperature": 0, "num_predict": 768},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0), trust_env=False
            ) as client:
                response = await client.post(f"{self._base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
            content = data["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
            return content
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise DetectError(f"Ollama の診断に失敗しました: {type(exc).__name__}") from None
