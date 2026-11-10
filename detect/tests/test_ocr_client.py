import base64
import json

import httpx
import pytest
import respx

from tkb_detect.errors import DetectError, ForbiddenEndpointError
from tkb_detect.ocr_client import MOCK_OCR_LINES, OcrClient, OcrConfig, OcrLine

BASE = "http://ocr.local"
IMAGE = b"\x89PNGfake"

PADDLEX_RESPONSE = {
    "errorCode": 0,
    "errorMsg": "Success",
    "result": {
        "ocrResults": [
            {
                "prunedResult": {
                    "rec_texts": ["新宿", "03-0000-0000"],
                    "rec_scores": [0.98, 0.87],
                    "rec_boxes": [[10, 20, 110, 60], [5, 70, 200, 95]],
                }
            }
        ]
    },
}


@pytest.mark.anyio
async def test_mock_mode_returns_fixed_lines_without_network() -> None:
    client = OcrClient(OcrConfig(base_url="", mock_mode=True))

    with respx.mock(assert_all_called=False) as router:
        lines = await client.recognize(IMAGE)

    assert lines == MOCK_OCR_LINES
    assert router.calls.call_count == 0


@pytest.mark.anyio
async def test_parses_paddlex_ocr_response() -> None:
    with respx.mock as router:
        route = router.post(f"{BASE}/ocr").respond(json=PADDLEX_RESPONSE)

        lines = await OcrClient(OcrConfig(base_url=BASE, mock_mode=False)).recognize(IMAGE)

    assert lines == [
        OcrLine(text="新宿", score=0.98, box=(10, 20, 110, 60)),
        OcrLine(text="03-0000-0000", score=0.87, box=(5, 70, 200, 95)),
    ]
    body = json.loads(route.calls.last.request.content)
    assert body == {"file": base64.b64encode(IMAGE).decode(), "fileType": 1}


@pytest.mark.anyio
async def test_raises_detect_error_on_http_error() -> None:
    with respx.mock as router:
        router.post(f"{BASE}/ocr").respond(status_code=503)

        with pytest.raises(DetectError):
            await OcrClient(OcrConfig(base_url=BASE, mock_mode=False)).recognize(IMAGE)


@pytest.mark.anyio
async def test_raises_detect_error_on_connection_failure() -> None:
    with respx.mock as router:
        router.post(f"{BASE}/ocr").mock(side_effect=httpx.ConnectTimeout("slow"))

        with pytest.raises(DetectError):
            await OcrClient(OcrConfig(base_url=BASE, mock_mode=False)).recognize(IMAGE)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"errorCode": 500, "errorMsg": "boom"},
        {"errorCode": 0, "result": {}},
        {
            "errorCode": 0,
            "result": {
                "ocrResults": [
                    {"prunedResult": {"rec_texts": ["a"], "rec_scores": [], "rec_boxes": []}}
                ]
            },
        },
    ],
)
async def test_raises_detect_error_on_unexpected_response(payload: object) -> None:
    with respx.mock as router:
        router.post(f"{BASE}/ocr").respond(json=payload)

        with pytest.raises(DetectError):
            await OcrClient(OcrConfig(base_url=BASE, mock_mode=False)).recognize(IMAGE)


def test_refuses_third_party_endpoint_outside_mock_mode() -> None:
    with pytest.raises(ForbiddenEndpointError):
        OcrClient(OcrConfig(base_url="https://generativelanguage.googleapis.com", mock_mode=False))


@pytest.mark.anyio
@pytest.mark.parametrize("status", [200, 404, 405])
async def test_is_reachable_when_the_server_answers(status: int) -> None:
    # 待ち受けていれば、/health が無い版（404・405）でも動いているとみなす
    with respx.mock as router:
        route = router.get(f"{BASE}/health").respond(status)

        assert await OcrClient(OcrConfig(base_url=BASE, mock_mode=False)).is_reachable(1) is True

    assert route.calls.last.request.content == b""  # 写真を送らない


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),  # 起動中
        httpx.ConnectError("refused"),  # 止まっている
        httpx.ConnectTimeout("timeout"),
    ],
)
async def test_is_reachable_is_false_when_the_server_does_not_answer(
    response: httpx.Response | Exception,
) -> None:
    with respx.mock as router:
        router.get(f"{BASE}/health").mock(side_effect=[response])

        assert await OcrClient(OcrConfig(base_url=BASE, mock_mode=False)).is_reachable(1) is False


@pytest.mark.anyio
async def test_is_reachable_is_true_in_mock_mode_without_network() -> None:
    with respx.mock(assert_all_called=False) as router:
        assert await OcrClient(OcrConfig(base_url="", mock_mode=True)).is_reachable(1) is True

    assert router.calls.call_count == 0
