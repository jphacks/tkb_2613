"""地域メッシュのコードと緯度経度の変換（jismesh を使う）。

jismesh の配列版は要素が 1 つのとき numpy 2 で削除された関数を呼んで失敗するので、
1 件ずつスカラー版を呼ぶ。
"""

import jismesh.utils as ju

# jismesh の次数：3次メッシュ（1km）、4次メッシュ（2分の1地域メッシュ、500m）
LEVEL_1KM = 3
LEVEL_500M = 4


def center(code: str) -> tuple[float, float]:
    """メッシュの中心の（緯度, 経度）。"""
    lat, lon = ju.to_meshpoint(code, 0.5, 0.5)
    return float(lat), float(lon)


def code_1km(lat: float, lon: float) -> str:
    return str(ju.to_meshcode(lat, lon, LEVEL_1KM))
