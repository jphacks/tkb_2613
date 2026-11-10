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
    # 送り先の許可リスト。None なら環境変数 MODEL_ALLOWED_HOST_SUFFIXES を読む（guard.py）
    allowed_hosts: tuple[str, ...] | None = None


class OcrClient:
    def __init__(self, config: OcrConfig) -> None:
        self._config = config
        # モックでは接続しないので、接続先の確認もしない
        self._base_url = (
            "" if config.mock_mode else ensure_team_endpoint(config.base_url, config.allowed_hosts)
        )

    async def recognize(self, image: bytes) -> list[OcrLine]:
        if self._config.mock_mode:
            return list(MOCK_OCR_LINES)

        payload = {"file": base64.b64encode(image).decode(), "fileType": PADDLEX_FILE_TYPE_IMAGE}
        return _parse_lines(await self._post(payload))

    async def is_reachable(self, timeout_s: float) -> bool:
        """OCR のサーバーが待ち受けているか（GET {OCR_BASE_URL}/health）。

        診断を始める前に、短い待ち時間で確かめる。写真は送らない。/health が無い版でも
        404・405 は待ち受けている証拠なので True にし、5xx（起動中など）と接続できないときは False。
        モックでは常に True。
        """
        if self._config.mock_mode:
            return True
        try:
            async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
                res = await client.get(f"{self._base_url}/health")
        except httpx.HTTPError:
            return False
        return res.status_code < 500

    async def _post(self, payload: dict[str, Any]) -> Any:
        try:
            # 環境変数のプロキシ（HTTP_PROXY など）を経由させない。送るのはガードで確認した先だけ
            async with httpx.AsyncClient(timeout=self._config.timeout_s, trust_env=False) as client:
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
