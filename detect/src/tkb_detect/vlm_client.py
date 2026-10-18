"""画像を読む言語モデル（vLLM, OpenAI 互換 API）の呼び出し。

応答の文字列をそのまま返す。手がかりの形式への変換はここでは行わない。
"""

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from tkb_detect.errors import DetectError
from tkb_detect.guard import ensure_team_endpoint

MOCK_VLM_TEXT = "（モック）駅名標「新宿」が写っています。"
DEFAULT_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class VlmConfig:
    base_url: str
    api_key: str
    model: str
    mock_mode: bool = True
    timeout_s: float = DEFAULT_TIMEOUT_S


class VlmClient:
    def __init__(self, config: VlmConfig) -> None:
        self._config = config
        # モックでは接続しないので、接続先の確認もしない
        self._base_url = "" if config.mock_mode else ensure_team_endpoint(config.base_url)

    async def complete(self, image: bytes, mime_type: str, prompt: str) -> str:
        if self._config.mock_mode:
            return MOCK_VLM_TEXT

        data = await self._post(self._build_payload(image, mime_type, prompt))
        return _extract_content(data)

    def _build_payload(self, image: bytes, mime_type: str, prompt: str) -> dict[str, Any]:
        data_url = f"data:{mime_type};base64,{base64.b64encode(image).decode()}"
        return {
            "model": self._config.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }

    async def _post(self, payload: dict[str, Any]) -> Any:
        headers = {}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_s) as client:
                res = await client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
                res.raise_for_status()
                return res.json()
        except httpx.HTTPStatusError as e:
            raise DetectError(f"VLM がエラーを返しました: {e.response.status_code}") from e
        except (httpx.HTTPError, ValueError) as e:
            # 例外の文言に本文が含まれないよう、型名だけを出す
            raise DetectError(f"VLM に接続できませんでした: {type(e).__name__}") from e


def _extract_content(data: Any) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise DetectError("VLM の応答が想定外の形式です") from e
    if not isinstance(content, str):
        raise DetectError("VLM の応答に本文がありません")
    return content
