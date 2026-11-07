from urllib.parse import urlparse

import pytest

from tkb_detect.errors import ForbiddenEndpointError
from tkb_detect.guard import ALLOWLIST_ENV_VAR, ensure_team_endpoint


@pytest.fixture
def no_env_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ALLOWLIST_ENV_VAR, raising=False)


# --- 許可リストが空のとき：loopback だけ（開発用）。それ以外はすべて拒否 ---


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/v1",
        "http://LOCALHOST:8000/v1/",
        "http://127.0.0.1:8000/v1",
        "http://127.0.0.2:8080",
        "http://[::1]:8000/v1",
    ],
)
def test_empty_allowlist_accepts_only_loopback(no_env_allowlist: None, url: str) -> None:
    assert ensure_team_endpoint(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:8080",  # 社内LAN・VPC 内でも、許可リストに書かなければ送らない
        "http://192.168.1.10:8000/v1",
        "https://gpu.example-team.dev/v1",
        "https://abc-8000.proxy.runpod.net/v1",
        "https://evil.example/v1",  # 拒否リスト方式には戻らない
        "http://localhost.evil.example/v1",
    ],
)
def test_empty_allowlist_rejects_everything_else(no_env_allowlist: None, url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url)


def test_blank_env_allowlist_counts_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOWLIST_ENV_VAR, " , ")
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint("https://evil.example/v1")


def test_explicit_empty_list_does_not_fall_back_to_env() -> None:
    # 環境変数（conftest で vlm.local）があっても、[] を渡したら空として扱う
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint("http://vlm.local/v1", allowed_host_suffixes=[])


# --- ホスト名の許可リスト：列挙したホストとそのサブドメイン ---


def test_hostname_allowlist_accepts_host_and_subdomains() -> None:
    suffixes = ["proxy.runpod.net"]
    for url in ("https://proxy.runpod.net/v1", "https://abc-8000.proxy.runpod.net/v1/"):
        assert ensure_team_endpoint(url, allowed_host_suffixes=suffixes) == url.rstrip("/")


def test_allowlist_entries_are_normalized() -> None:
    assert (
        ensure_team_endpoint("https://GPU.Team.dev/v1", allowed_host_suffixes=[" gpu.team.dev. "])
        == "https://GPU.Team.dev/v1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1",
        "http://localhost:8000/v1",  # 許可リストを設定したら loopback も明示が要る
        "https://proxy.runpod.net.evil.com/v1",  # 接尾辞の偽装
        "https://evilproxy.runpod.net/v1",  # 「.」の境界をまたぐ一致
    ],
)
def test_hostname_allowlist_rejects_others(url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=["proxy.runpod.net"])


# --- IP の許可リスト：完全一致だけ ---


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("http://10.0.2.15:8000/v1", "10.0.2.15"),  # VPC 内の GPU
        ("http://10.0.2.15:8080", "10.0.2.15"),  # 同じ GPU の OCR
        ("http://[fd00::15]:8000/v1", "fd00::15"),
        ("http://[fd00::15]:8000/v1", "fd00:0:0:0:0:0:0:15"),  # 書き方が違っても同じ IP
    ],
)
def test_ip_allowlist_accepts_exact_ip(url: str, allowed: str) -> None:
    assert ensure_team_endpoint(url, allowed_host_suffixes=[allowed]) == url


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("http://110.0.2.15:8000/v1", "10.0.2.15"),  # 後ろからの一致では通さない
        ("http://10.0.2.150:8000/v1", "10.0.2.15"),
        ("http://10.0.2.16:8000/v1", "10.0.2.15"),
        ("http://1.0.2.15:8000/v1", "0.2.15"),  # IP の一部を書いても一致しない
        ("http://10.0.2.15:8000/v1", "15"),  # IP にホスト名の接尾辞は当てない
        ("http://10.0.2.15:8000/v1", "2.15"),
    ],
)
def test_ip_allowlist_rejects_partial_or_suffix_match(url: str, allowed: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=[allowed])


# --- 特別用途の IP は、許可リストに書いても常に拒否 ---


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # クラウドのメタデータ
        "http://169.254.0.1/",
        "http://169.254.255.255/",
        "http://[::ffff:169.254.169.254]/",  # IPv4 を埋め込んだ IPv6
        "http://[fe80::1]:8000/v1",  # IPv6 リンクローカル
        "http://0.0.0.0:8000/v1",
        "http://224.0.0.1/",
    ],
)
def test_special_ips_are_always_rejected(url: str) -> None:
    host = urlparse(url).hostname or ""
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=[host])
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=[])


# --- 既知の第三者 AI サービスは、許可リストに書いても拒否 ---

THIRD_PARTY_LISTED = ["openai.com", "googleapis.com", "anthropic.com", "azure.com"]


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
def test_third_party_ai_services_are_rejected_even_if_listed(url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=THIRD_PARTY_LISTED)
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=[])


# --- URL の形 ---


@pytest.mark.parametrize("url", ["", "ftp://localhost", "localhost:8000", "http://"])
def test_rejects_missing_or_non_http_url(url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=["localhost"])


# --- 環境変数 ---


def test_env_var_configures_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOWLIST_ENV_VAR, "proxy.runpod.net, 10.0.2.15")
    assert (
        ensure_team_endpoint("https://p-8000.proxy.runpod.net/v1")
        == "https://p-8000.proxy.runpod.net/v1"
    )
    assert ensure_team_endpoint("http://10.0.2.15:8080") == "http://10.0.2.15:8080"
    for url in ("https://api.openai.com/v1", "http://localhost:8000/v1", "http://110.0.2.15/"):
        with pytest.raises(ForbiddenEndpointError):
            ensure_team_endpoint(url)


# --- 書き方の抜け道（レビューの指摘） ---


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("http://[fe80::1%25eth0]:8000/v1", "fe80::1%25eth0"),  # ゾーン ID つきのリンクローカル
        ("http://[fd00::15%25eth0]:8000/v1", "fd00::15%25eth0"),
        ("http://[64:ff9b::a9fe:a9fe]/", "64:ff9b::a9fe:a9fe"),  # NAT64 で 169.254.169.254
        ("http://[2002:a9fe:a9fe::1]/", "2002:a9fe:a9fe::1"),  # 6to4
    ],
)
def test_ip_forms_that_hide_another_address_are_always_rejected(url: str, allowed: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=[allowed])


@pytest.mark.parametrize(
    "url",
    [
        "http://vlm.local /v1",  # 空白
        "http://vlm.local/v1\n",  # 改行
        "http://vlm.local\t:8000/v1",
        "http://vlm.local:abc/v1",  # 数字でないポート
        "http://vlm.local:99999/v1",  # 範囲外のポート
    ],
)
def test_malformed_urls_are_rejected(url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=["vlm.local"])


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.example\\@vlm.local/v1",  # 実際の接続先は vlm.local（httpx も同じ）
        "http://user@vlm.local/v1",
    ],
)
def test_userinfo_does_not_change_the_checked_host(url: str) -> None:
    assert ensure_team_endpoint(url, allowed_host_suffixes=["vlm.local"]) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://vlm.local\\@evil.example/v1",
        "http://user@vlm.local@evil.example/v1",
    ],
)
def test_userinfo_tricks_pointing_elsewhere_are_rejected(url: str) -> None:
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint(url, allowed_host_suffixes=["vlm.local"])


def test_trailing_dot_localhost_counts_as_loopback(no_env_allowlist: None) -> None:
    assert ensure_team_endpoint("http://localhost.:8000/v1") == "http://localhost.:8000/v1"


def test_ipv4_mapped_entry_does_not_match_plain_ipv4() -> None:
    # 書き方の違う IP は、同じ書き方で許可リストに書いたときだけ一致する（通さない側に倒す）
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint("http://10.0.2.15/", allowed_host_suffixes=["::ffff:10.0.2.15"])
    with pytest.raises(ForbiddenEndpointError):
        ensure_team_endpoint("http://[::ffff:10.0.2.15]/", allowed_host_suffixes=["10.0.2.15"])
