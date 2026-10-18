from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.detect import MAX_IMAGE_BYTES
from tkb_api.schemas import DetectResponse

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _client(Settings(mock_mode=True)) as c:
        yield c


def test_health_returns_ok(client: TestClient) -> None:
    res = client.get("/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "mock_mode": True}


def test_detect_returns_fixed_clues_in_mock_mode(client: TestClient) -> None:
    res = client.post("/api/detect", content=JPEG_BYTES, headers={"Content-Type": "image/jpeg"})

    assert res.status_code == 200
    body = DetectResponse.model_validate(res.json())
    assert len(body.clues) > 0


def test_detect_rejects_unsupported_content_type(client: TestClient) -> None:
    res = client.post("/api/detect", content=b"hello", headers={"Content-Type": "text/plain"})

    assert res.status_code == 415


def test_detect_rejects_empty_body(client: TestClient) -> None:
    res = client.post("/api/detect", content=b"", headers={"Content-Type": "image/jpeg"})

    assert res.status_code == 400


def test_detect_rejects_oversized_body(client: TestClient) -> None:
    big = b"\x00" * (MAX_IMAGE_BYTES + 1)

    res = client.post("/api/detect", content=big, headers={"Content-Type": "image/png"})

    assert res.status_code == 413


def test_detect_is_not_implemented_outside_mock_mode() -> None:
    with _client(Settings(mock_mode=False)) as c:
        res = c.post("/api/detect", content=JPEG_BYTES, headers={"Content-Type": "image/jpeg"})

    assert res.status_code == 501
