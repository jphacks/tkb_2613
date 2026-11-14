from jismesh.utils import to_meshcode

from tkb_engine.gazetteer import Gazetteer


def _code(latitude: float, longitude: float) -> str:
    return str(int(to_meshcode(latitude, longitude, 3)))


def test_gazetteer_builds_japan_mesh_union_and_checks_domestic_and_island_points() -> None:
    tokyo = (35.123456, 139.123456)
    okinawa = (26.2124, 127.6809)
    gazetteer = Gazetteer(
        muni_meshes={
            "13101": {f"{_code(*tokyo)}*"},
            "47201": {_code(*okinawa)},
        }
    )

    assert gazetteer.jp_meshes == {_code(*tokyo), _code(*okinawa)}
    assert gazetteer.is_japan_mesh_coordinate(*tokyo)
    assert gazetteer.is_japan_mesh_coordinate(*okinawa)
    # Both are inside the previous coarse Japan bounding box, but not in the mesh table.
    assert not gazetteer.is_japan_mesh_coordinate(34.0, 126.0)
    assert not gazetteer.is_japan_mesh_coordinate(37.0, 127.0)


def test_gazetteer_fails_closed_when_mesh_data_is_absent() -> None:
    tokyo = (35.123456, 139.123456)
    gazetteer = Gazetteer(jp_meshes=set())

    assert not gazetteer.is_japan_mesh_coordinate(*tokyo)
