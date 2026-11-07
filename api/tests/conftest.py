"""api のテストを手元の設定に左右されないようにする。

Settings は既定でリポジトリ直下の .env と環境変数を読む。手元の .env が MOCK_MODE=0 などだと、
`Depends(get_settings)` で設定を読み直すルート（ログインなど）が本番の動きになり、
CI では通るテストが手元でだけ落ちる。そこで、テストでは .env を読まず、Settings の項目に当たる
環境変数も消す。個々のテストで必要な値は、Settings(...) に直接渡すか monkeypatch で入れる。

tkb_api.main は import したときに create_app() を呼ぶので、テストのモジュールより先に
読まれるこのファイルの上のほうで済ませておく。
"""

import os
from collections.abc import Iterator

import pytest

from tkb_api.config import Settings, get_settings

Settings.model_config["env_file"] = None
for _name in Settings.model_fields:
    os.environ.pop(_name.upper(), None)
get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_settings_cache() -> Iterator[None]:
    """テストの間で get_settings() の結果を持ち越さない（monkeypatch した環境変数を反映させる）。"""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
