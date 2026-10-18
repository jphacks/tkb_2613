import base64
import json

import httpx
import pytest
import respx

from tkb_detect.errors import DetectError, ForbiddenEndpointError
from tkb_detect.vlm_client import MOCK_VLM_TEXT, VlmClient, VlmConfig

BASE = "http://vlm.local/v1"
IMAGE = b"\xff\xd8\xff\xe0fake"


def _config(**overrides: object) -> VlmConfig:
    params: dict[str, object] = {
        "base_url": BASE,
        "api_key": "secret",
        "model": "qwen-vl",
        "mock_mode": False,
    }
    return VlmConfig(**{**params, **overrides})  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_mock_mode_returns_fixed_text_without_network() -> None:
    client = VlmClient(VlmConfig(base_url="", api_key="", model="", mock_mode=True))

    with respx.mock(assert_all_called=False) as router:
        text = await client.complete(IMAGE, "image/jpeg", "何が写っている？")

    assert text == MOCK_VLM_TEXT
    assert router.calls.call_count == 0


@pytest.mark.anyio
async def test_sends_openai_compatible_request_with_image() -> None:
    with respx.mock as router:
        route = router.post(f"{BASE}/chat/completions").respond(
            json={"choices": [{"message": {"content": "駅名標: 新宿"}}]}
        )

        text = await VlmClient(_config()).complete(IMAGE, "image/jpeg", "手がかりは？")

    assert text == "駅名標: 新宿"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret"
    body = json.loads(request.content)
    assert body["model"] == "qwen-vl"
    content = body["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "手がかりは？"}
    expected_url = "data:image/jpeg;base64," + base64.b64encode(IMAGE).decode()
    assert content[1] == {"type": "image_url", "image_url": {"url": expected_url}}


@pytest.mark.anyio
async def test_omits_authorization_header_when_no_api_key() -> None:
    with respx.mock as router:
        route = router.post(f"{BASE}/chat/completions").respond(
            json={"choices": [{"message": {"content": "ok"}}]}
        )

        await VlmClient(_config(api_key="")).complete(IMAGE, "image/png", "p")

    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.anyio
async def test_raises_detect_error_on_http_error() -> None:
    with respx.mock as router:
        router.post(f"{BASE}/chat/completions").respond(status_code=500)

        with pytest.raises(DetectError):
            await VlmClient(_config()).complete(IMAGE, "image/jpeg", "p")


@pytest.mark.anyio
async def test_raises_detect_error_on_connection_failure() -> None:
    with respx.mock as router:
        router.post(f"{BASE}/chat/completions").mock(side_effect=httpx.ConnectError("down"))

        with pytest.raises(DetectError):
            await VlmClient(_config()).complete(IMAGE, "image/jpeg", "p")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}],
)
async def test_raises_detect_error_on_unexpected_response(payload: object) -> None:
    with respx.mock as router:
        router.post(f"{BASE}/chat/completions").respond(json=payload)

        with pytest.raises(DetectError):
            await VlmClient(_config()).complete(IMAGE, "image/jpeg", "p")


def test_refuses_third_party_endpoint_outside_mock_mode() -> None:
    with pytest.raises(ForbiddenEndpointError):
        VlmClient(_config(base_url="https://api.openai.com/v1"))
