import json
import zipfile
from pathlib import Path

from tkb_data_prep import boundaries
from tkb_data_prep.config import Paths


def _square(code: str, lon: float, lat: float, size: float = 0.01) -> dict[str, object]:
    ring = [[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat]]
    return {
        "type": "Feature",
        "properties": {"N03_001": "東京都", "N03_004": "x", "N03_007": code},
        "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]},
    }


def test_locator_finds_the_municipality_that_contains_the_point() -> None:
    locator = boundaries.Locator.from_geojson(
        [
            {
                "features": [
                    _square("13105", 139.76, 35.71),
                    _square("13106", 139.77, 35.71),
                    _square(None, 139.78, 35.71),  # type: ignore[arg-type]
                ]
            }
        ]
    )

    assert locator.locate(35.715, 139.765) == "13105"
    assert locator.locate(35.715, 139.775) == "13106"
    assert locator.locate(35.715, 139.785) is None  # コードのない「所属未定地」
    assert locator.locate(36.0, 140.0) is None


def test_load_reads_every_prefecture_zip_and_is_empty_without_them(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path)
    assert boundaries.load(paths) is None

    zip_path = paths.ksj_boundary_zip("13")
    zip_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "N03-20260101_13.geojson", json.dumps({"features": [_square("13105", 139.76, 35.71)]})
        )

    locator = boundaries.load(paths)
    assert locator is not None
    assert locator.locate(35.715, 139.765) == "13105"
