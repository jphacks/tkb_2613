"""画像を読む言語モデル（vLLM, OpenAI 互換 API）の呼び出し。

応答の文字列をそのまま返す。手がかりの形式への変換はここでは行わない。
"""

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from tkb_detect.errors import DetectError, OutputCutOffError
from tkb_detect.guard import ensure_team_endpoint

MOCK_VLM_TEXT = "（モック）駅名標「新宿」が写っています。"
MOCK_VLM_JSON = '{"clues": []}'
DEFAULT_TIMEOUT_S = 60.0
# Qwen3 系は既定で思考モードが入り遅くなるため、毎回切る
CHAT_TEMPLATE_KWARGS = {"enable_thinking": False}


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

    async def complete(
        self,
        image: bytes,
        mime_type: str,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        repetition_penalty: float | None = None,
    ) -> str:
        """画像と指示を送る。json_schema を渡すと、その形の JSON だけを返させる。

        max_tokens に達して出力が途中で切れたときは OutputCutOffError にする。
        """
        if self._config.mock_mode:
            return MOCK_VLM_TEXT if json_schema is None else MOCK_VLM_JSON

        data_url = f"data:{mime_type};base64,{base64.b64encode(image).decode()}"
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        payload = self._build_payload(content, system, json_schema, max_tokens, repetition_penalty)
        data = await self._post(payload)
        return _extract_content(data)

    async def complete_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        repetition_penalty: float | None = None,
    ) -> str:
        """画像なしで文字だけを送る（投稿の本文の読み取り用）。"""
        if self._config.mock_mode:
            return MOCK_VLM_TEXT if json_schema is None else MOCK_VLM_JSON

        payload = self._build_payload(prompt, system, json_schema, max_tokens, repetition_penalty)
        data = await self._post(payload)
        return _extract_content(data)

    def _build_payload(
        self,
        user_content: str | list[dict[str, Any]],
        system: str | None,
        json_schema: dict[str, Any] | None,
        max_tokens: int | None = None,
        repetition_penalty: float | None = None,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})

        payload: dict[str, Any] = {
            "model": self._config.model,
            "temperature": 0,
            "messages": messages,
            "chat_template_kwargs": dict(CHAT_TEMPLATE_KWARGS),
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if repetition_penalty is not None:
            payload["repetition_penalty"] = repetition_penalty
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "clues", "schema": json_schema},
            }
        return payload

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
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise DetectError("VLM の応答が想定外の形式です") from e
    if choice.get("finish_reason") == "length":
        raise OutputCutOffError("VLM の出力が長すぎて途中で切れました")
    if not isinstance(content, str):
        raise DetectError("VLM の応答に本文がありません")
    return content
