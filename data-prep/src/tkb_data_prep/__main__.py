"""取得済みの公開データを変換して data/processed/ に Parquet で書き出す。

uv run python -m tkb_data_prep
"""

import sys

from tkb_data_prep import (
    area_codes,
    boundaries,
    bus_stops,
    corporations,
    households,
    muni_mesh,
    postal,
    school_districts,
    schools,
    shelters,
    stations,
)
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.summary import Tables, report


def run(paths: Paths) -> Tables:
    munis = muni_mesh.load(paths)
    allowed = muni_mesh.meshes(munis)
    postals = postal.load(paths)
    loaded = households.load(paths, allowed)
    station_rows = stations.load(paths, allowed)
    converted = area_codes.load(paths, area_codes.NameIndex.build(munis, postals))
    school_rows = schools.load(paths, postals)
    shelter_rows = shelters.load(paths, postals)
    locator = boundaries.load(paths)
    district_rows = school_districts.load(paths, postals, locator)
    bus_stop_rows = bus_stops.load(paths, munis, postals, locator)

    out = paths.out_dir
    muni_mesh.write(munis, out / "muni_mesh.parquet")
    households.write(loaded.rows, out / "households_500m.parquet")
    postal.write(postals, out / "postal.parquet")
    stations.write(station_rows, out / "stations.parquet")
    area_codes.write(converted.rows, out / "area_codes.parquet")
    schools.write(school_rows, out / "schools.parquet")
    shelters.write(shelter_rows, out / "shelters.parquet")
    school_districts.write(district_rows, out / "school_districts.parquet")
    bus_stops.write(bus_stop_rows, out / "bus_stops.parquet")
    corporation_result = corporations.build(paths, out / "corporations.sqlite")

    return Tables(
        muni_mesh=munis,
        households=loaded.rows,
        estat_first_meshes=loaded.first_meshes,
        postal=postals,
        stations=station_rows,
        area_codes=converted.rows,
        area_code_problems=converted.problems,
        schools=school_rows,
        shelters=shelter_rows,
        school_districts=district_rows,
        bus_stops=bus_stop_rows,
        corporations=corporation_result,
    )


def main() -> int:
    paths = Paths()
    try:
        tables = run(paths)
    except DataPrepError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    print(f"{paths.out_dir} に書き出しました\n")
    print("\n".join(report(tables)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
