import pytest

from tkb_detect.errors import ForbiddenEndpointError
from tkb_detect.guard import ensure_team_endpoint


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/v1",
        "http://10.0.0.5:8080",
        "https://gpu.example-team.dev/v1/",
    ],
)
def test_accepts_team_server_and_strips_trailing_slash(url: str) -> None:
    assert ensure_team_endpoint(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://generativelanguage.googleapis.com/v1beta",
        "https://api.anthropic.com/v1",
        "https://foo.openai.azure.com/openai",
        "https://API.OPENAI.COM/v1",
    ],
)
def test_rejects_third_party_ai_services(url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url)


@pytest.mark.parametrize("url", ["", "ftp://localhost", "localhost:8000"])
def test_rejects_missing_or_non_http_url(url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url)
