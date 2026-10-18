"""OCR（PP-OCRv5 の HTTP サービス）の呼び出し。

PaddleX の OCR サービスの形式（POST /ocr）を想定する。
読み取った行をそのまま返す。手がかりの形式への変換はここでは行わない。
"""

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from tkb_detect.errors import DetectError
from tkb_detect.guard import ensure_team_endpoint

DEFAULT_TIMEOUT_S = 30.0
PADDLEX_FILE_TYPE_IMAGE = 1


@dataclass(frozen=True)
class OcrLine:
    text: str
    score: float
    # 画像上の矩形 [左上x, 左上y, 右下x, 右下y]（ピクセル）
    box: tuple[int, int, int, int]


MOCK_OCR_LINES = [
    OcrLine(text="新宿", score=0.98, box=(120, 80, 340, 150)),
    OcrLine(text="03-0000-0000", score=0.87, box=(400, 300, 560, 330)),
]


@dataclass(frozen=True)
class OcrConfig:
    base_url: str
    mock_mode: bool = True
    timeout_s: float = DEFAULT_TIMEOUT_S


class OcrClient:
    def __init__(self, config: OcrConfig) -> None:
        self._config = config
        # モックでは接続しないので、接続先の確認もしない
        self._base_url = "" if config.mock_mode else ensure_team_endpoint(config.base_url)

    async def recognize(self, image: bytes) -> list[OcrLine]:
        if self._config.mock_mode:
            return list(MOCK_OCR_LINES)

        payload = {"file": base64.b64encode(image).decode(), "fileType": PADDLEX_FILE_TYPE_IMAGE}
        return _parse_lines(await self._post(payload))

    async def _post(self, payload: dict[str, Any]) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_s) as client:
                res = await client.post(f"{self._base_url}/ocr", json=payload)
                res.raise_for_status()
                return res.json()
        except httpx.HTTPStatusError as e:
            raise DetectError(f"OCR がエラーを返しました: {e.response.status_code}") from e
        except (httpx.HTTPError, ValueError) as e:
            # 例外の文言に本文が含まれないよう、型名だけを出す
            raise DetectError(f"OCR に接続できませんでした: {type(e).__name__}") from e


def _parse_lines(data: Any) -> list[OcrLine]:
    try:
        if data["errorCode"] != 0:
            raise DetectError(f"OCR がエラーを返しました: {data['errorCode']}")
        lines: list[OcrLine] = []
        for result in data["result"]["ocrResults"]:
            pruned = result["prunedResult"]
            texts, scores, boxes = pruned["rec_texts"], pruned["rec_scores"], pruned["rec_boxes"]
            if not len(texts) == len(scores) == len(boxes):
                raise DetectError("OCR の応答で行数がそろっていません")
            lines.extend(
                OcrLine(
                    text=str(t), score=float(s), box=(int(b[0]), int(b[1]), int(b[2]), int(b[3]))
                )
                for t, s, b in zip(texts, scores, boxes, strict=True)
            )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise DetectError("OCR の応答が想定外の形式です") from e
    return lines
