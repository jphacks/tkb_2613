"""取得済みの公開データを変換して data/processed/ に Parquet で書き出す。

uv run python -m tkb_data_prep
"""

import sys

from tkb_data_prep import area_codes, households, muni_mesh, postal, stations
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

    out = paths.out_dir
    muni_mesh.write(munis, out / "muni_mesh.parquet")
    households.write(loaded.rows, out / "households_500m.parquet")
    postal.write(postals, out / "postal.parquet")
    stations.write(station_rows, out / "stations.parquet")
    area_codes.write(converted.rows, out / "area_codes.parquet")

    return Tables(
        muni_mesh=munis,
        households=loaded.rows,
        estat_first_meshes=loaded.first_meshes,
        postal=postals,
        stations=station_rows,
        area_codes=converted.rows,
        area_code_problems=converted.problems,
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
