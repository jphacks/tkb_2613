import pytest

from tkb_data_prep import mesh


def test_center_of_500m_mesh() -> None:
    lat, lon = mesh.center("533945091")

    # 500m メッシュは 緯度 15 秒 × 経度 22.5 秒。中心は南西の角からその半分だけ離れる
    assert lat == pytest.approx(35 + 40 / 60 + 7.5 / 3600)
    assert lon == pytest.approx(139 + 44.25 / 60 + 11.25 / 3600)


def test_center_of_1km_mesh_maps_back_to_itself() -> None:
    lat, lon = mesh.center("53394509")

    assert mesh.code_1km(lat, lon) == "53394509"


def test_code_1km_of_shinjuku_station() -> None:
    assert mesh.code_1km(35.6896, 139.7006) == "53394526"
