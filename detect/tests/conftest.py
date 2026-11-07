import pytest

from tkb_detect.guard import ALLOWLIST_ENV_VAR


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _team_endpoint_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """テストの架空のモデルサーバー（vlm.local、ocr.local）を許可リストに入れる。

    本番と同じく、許可リストを明示しないと送り先は loopback だけになるため。
    手元のシェルの設定にも左右されないよう、毎回ここで決める。
    """
    monkeypatch.setenv(ALLOWLIST_ENV_VAR, "vlm.local,ocr.local")
