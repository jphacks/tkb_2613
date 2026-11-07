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


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # クラウドのメタデータ（リンクローカル）
        "http://169.254.1.1/",
        "http://[fe80::1]:8000/v1",  # IPv6 リンクローカル
        "http://0.0.0.0:8000/v1",  # 未指定アドレス
        "http://224.0.0.1/",  # マルチキャスト
    ],
)
def test_rejects_link_local_and_special_ips(url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/v1",  # loopback は許可（開発）
        "http://10.0.0.5:8080",  # 社内LAN のチームサーバーは許可
        "http://192.168.1.10:8000/v1",
    ],
)
def test_accepts_loopback_and_private_lan(url: str) -> None:
    assert ensure_team_endpoint(url) == url.rstrip("/")


def test_strict_allowlist_accepts_only_listed_suffixes() -> None:
    suffixes = ["proxy.runpod.net"]
    assert (
        ensure_team_endpoint("https://abc-8000.proxy.runpod.net/v1", allowed_host_suffixes=suffixes)
        == "https://abc-8000.proxy.runpod.net/v1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1",  # リストに無い任意の公開ホスト
        "http://localhost:8000/v1",  # 厳格モードでは loopback も明示が要る
        "https://proxy.runpod.net.evil.com/v1",  # 接尾辞偽装
    ],
)
def test_strict_allowlist_rejects_others(url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=["proxy.runpod.net"])


def test_strict_allowlist_still_blocks_link_local() -> None:
    # 許可リストを設定しても、リンクローカル/メタデータIPは常に拒否
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint("http://169.254.169.254/", allowed_host_suffixes=["169.254.169.254"])


def test_env_var_configures_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_ALLOWED_HOST_SUFFIXES", "proxy.runpod.net, localhost")
    assert (
        ensure_team_endpoint("https://p-8000.proxy.runpod.net/v1")
        == "https://p-8000.proxy.runpod.net/v1"
    )
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint("https://api.openai.com/v1")
