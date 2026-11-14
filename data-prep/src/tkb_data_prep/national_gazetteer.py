"""Generate a small Japan-wide station/postal/municipality gazetteer.

This command is deliberately separate from ``make data``: it does not download
or process census, school, corporation, or other large datasets.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, TextIO

import pyarrow as pa
import pyarrow.parquet as pq

from tkb_data_prep import muni_mesh, postal, stations
from tkb_data_prep.config import ALL_PREFECTURE_CODES, Paths
from tkb_data_prep.errors import DataPrepError


def _read_mesh_rows(path: Path) -> Iterator[list[str]]:
    """Read a small official CSV incrementally; retain legacy UTF-8/CP932 handling."""
    sample = path.read_bytes()[:4096]
    encoding = "utf-8-sig"
    try:
        sample.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp932"
    with path.open("r", encoding=encoding, newline="") as source:
        yield from (row for row in csv.reader(source) if row)


POSTAL_URL = "https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip"
MESH_URL = "https://www.stat.go.jp/data/mesh/csv/{prefecture}.csv"
STATIONS_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N02/N02-24/N02-24_GML.zip"

# Refuse unexpectedly large sources. The normal inputs are ~2 MB postal, 12.1 MB
# railway zip, and small prefecture CSVs. The decompressed station member has a
# separate cap because it is parsed as a stream.
MAX_POSTAL_ZIP_BYTES = 4 * 1024 * 1024
MAX_POSTAL_MEMBER_BYTES = 24 * 1024 * 1024
MAX_STATION_ZIP_BYTES = 32 * 1024 * 1024
MAX_MESH_CSV_BYTES = 4 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 64 * 1024 * 1024
MAX_STATION_MEMBER_BYTES = 512 * 1024 * 1024
MAX_FEATURE_BYTES = 2 * 1024 * 1024
MAX_POSTAL_ROWS = 250_000
MAX_MESH_ROWS = 1_000_000
MAX_STATION_ROWS = 100_000
MAX_STATION_SEGMENTS = 3_000_000
BATCH_ROWS = 10_000
MIN_OUTPUT_FREE_BYTES = 256 * 1024 * 1024


@dataclass
class _Track:
    segments: list[tuple[float, float, float, float]] = field(default_factory=list)
    point_count: int = 0
    lat_sum: float = 0.0
    lon_sum: float = 0.0

    def add_line(self, points: list[stations.Point]) -> None:
        self.point_count += len(points)
        self.lat_sum += sum(lat for _, lat in points)
        self.lon_sum += sum(lon for lon, _ in points)
        for (lon1, lat1), (lon2, lat2) in pairwise(points):
            self.segments.append((lon1, lat1, lon2, lat2))


def _iter_features(source: TextIO) -> Iterator[dict[str, Any]]:
    """Decode GeoJSON feature objects incrementally, bounding parser memory."""
    decoder = json.JSONDecoder()
    buffer = ""
    eof = False

    def read_more() -> None:
        nonlocal buffer, eof
        chunk = source.read(64 * 1024)
        if chunk:
            buffer += chunk
        else:
            eof = True

    while '"features"' not in buffer and not eof:
        read_more()
    marker = buffer.find('"features"')
    if marker < 0:
        raise DataPrepError("N02 GeoJSON に features がありません")
    array_start = buffer.find("[", marker)
    while array_start < 0 and not eof:
        read_more()
        array_start = buffer.find("[", marker)
    if array_start < 0:
        raise DataPrepError("N02 GeoJSON の features が配列ではありません")
    buffer = buffer[array_start + 1 :]

    while True:
        buffer = buffer.lstrip(" \t\r\n,")
        if not buffer and not eof:
            read_more()
            continue
        if buffer.startswith("]"):
            return
        if not buffer:
            raise DataPrepError("N02 GeoJSON の features 配列が閉じていません")
        try:
            feature, end = decoder.raw_decode(buffer)
        except json.JSONDecodeError:
            if eof:
                raise DataPrepError("N02 GeoJSON の feature が不正です") from None
            if len(buffer.encode("utf-8")) > MAX_FEATURE_BYTES:
                raise DataPrepError("N02 GeoJSON の feature が容量上限を超えました") from None
            read_more()
            continue
        if not isinstance(feature, dict):
            raise DataPrepError("N02 GeoJSON の feature が object ではありません")
        yield feature
        buffer = buffer[end:]


def _load_stations(paths: Paths, allowed_meshes: frozenset[str]) -> list[stations.Station]:
    path = paths.stations_zip
    if path.stat().st_size > MAX_STATION_ZIP_BYTES:
        raise DataPrepError(f"{path}: zip が上限 {MAX_STATION_ZIP_BYTES} bytes を超えています")
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.endswith(stations.GEOJSON_SUFFIX)]
        if len(members) != 1:
            raise DataPrepError(f"{path}: 駅GeoJSONが1つではありません: {members}")
        member = archive.getinfo(members[0])
        if member.file_size > MAX_STATION_MEMBER_BYTES:
            raise DataPrepError(
                f"{path}: 展開後の駅GeoJSONが上限 {MAX_STATION_MEMBER_BYTES} bytes を超えています"
            )
        tracks: dict[stations._Key, _Track] = {}
        segment_count = 0
        with (
            archive.open(member) as raw,
            __import__("io").TextIOWrapper(raw, encoding="utf-8") as stream,
        ):
            for feature in _iter_features(stream):
                key = stations._key(feature.get("properties") or {})
                geometry = feature.get("geometry") or {}
                kind = geometry.get("type")
                coords = geometry.get("coordinates") or []
                if kind == "LineString" and coords:
                    lines = [coords]
                elif kind == "MultiLineString" and coords:
                    lines = coords
                else:
                    raise DataPrepError(
                        f"{key.station_name}（{key.line_name}）: 想定外の形状 {kind}"
                    )
                track = tracks.setdefault(key, _Track())
                for coordinates in lines:
                    points = stations._points(coordinates)
                    segment_count += max(0, len(points) - 1)
                    if segment_count > MAX_STATION_SEGMENTS:
                        raise DataPrepError(
                            f"駅GeoJSONの線分数が上限 {MAX_STATION_SEGMENTS} を超えています"
                        )
                    track.add_line(points)

    rows: list[stations.Station] = []
    for key, track in tracks.items():
        if not track.point_count:
            continue
        mean_lat = track.lat_sum / track.point_count
        shrink = math.cos(math.radians(mean_lat))
        total = lon_sum = lat_sum = 0.0
        for lon1, lat1, lon2, lat2 in track.segments:
            length = math.hypot((lon2 - lon1) * shrink, lat2 - lat1)
            total += length
            lon_sum += length * (lon1 + lon2) / 2
            lat_sum += length * (lat1 + lat2) / 2
        if total:
            lat, lon = lat_sum / total, lon_sum / total
        else:
            lat, lon = mean_lat, track.lon_sum / track.point_count
        station = stations.Station(
            key.station_code, key.station_name, key.line_name, key.operator, lat, lon
        )
        if station.mesh_1km in allowed_meshes:
            rows.append(station)
            if len(rows) > MAX_STATION_ROWS:
                raise DataPrepError(f"駅の行数が上限 {MAX_STATION_ROWS} を超えています")
    return rows


def _download(url: str, destination: Path, max_bytes: int) -> None:
    if destination.exists():
        if not destination.is_file() or destination.stat().st_size == 0:
            raise DataPrepError(f"取得先が空またはファイルではありません: {destination}")
        if destination.stat().st_size > max_bytes:
            raise DataPrepError(f"取得済みファイルが容量上限を超えています: {destination}")
        print(f"取得済み: {destination}")
        return
    partial = destination.with_name(destination.name + ".part")
    if partial.exists():
        raise DataPrepError(f"一時ファイルが既にあります（上書きしません）: {partial}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(  # noqa: S310 - URLs are fixed official endpoints above.
        url, headers={"User-Agent": "tkb-data-prep/1.0"}
    )
    with (
        urllib.request.urlopen(request, timeout=30) as response,  # noqa: S310
        partial.open("xb") as output,
    ):
        declared = response.headers.get("Content-Length")
        if declared is not None and int(declared) > max_bytes:
            raise DataPrepError(f"ダウンロードが容量上限を超えています: {url}")
        total = 0
        while chunk := response.read(64 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise DataPrepError(f"ダウンロードが容量上限を超えています: {url}")
            output.write(chunk)
    if partial.stat().st_size == 0:
        raise DataPrepError(f"空ファイルを取得しました: {url}")
    partial.rename(destination)


def fetch(paths: Paths) -> None:
    _download(POSTAL_URL, paths.postal_zip, MAX_POSTAL_ZIP_BYTES)
    _download(STATIONS_URL, paths.stations_zip, MAX_STATION_ZIP_BYTES)
    for code in ALL_PREFECTURE_CODES:
        _download(MESH_URL.format(prefecture=code), paths.stat_mesh_csv(code), MAX_MESH_CSV_BYTES)
    total = paths.postal_zip.stat().st_size + paths.stations_zip.stat().st_size
    total += sum(paths.stat_mesh_csv(code).stat().st_size for code in ALL_PREFECTURE_CODES)
    if total > MAX_TOTAL_INPUT_BYTES:
        raise DataPrepError(f"入力合計が上限 {MAX_TOTAL_INPUT_BYTES} bytes を超えています")


def _write_batched(rows: list[Any], schema: pa.Schema, destination: Path) -> None:
    """Write Parquet in small Arrow batches without building a full Arrow table."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with pq.ParquetWriter(destination, schema, compression="zstd") as writer:
        for offset in range(0, len(rows), BATCH_ROWS):
            batch = rows[offset : offset + BATCH_ROWS]
            columns = {field.name: [getattr(row, field.name) for row in batch] for field in schema}
            writer.write_table(pa.table(columns, schema=schema), row_group_size=BATCH_ROWS)


def build(paths: Paths) -> tuple[int, int, int]:
    input_files = [paths.postal_zip, paths.stations_zip]
    input_files.extend(paths.stat_mesh_csv(code) for code in ALL_PREFECTURE_CODES)
    missing = [path for path in input_files if not path.is_file()]
    if missing:
        raise DataPrepError("全国Gazetteerの入力がありません: " + ", ".join(map(str, missing[:5])))
    total = sum(path.stat().st_size for path in input_files)
    if total > MAX_TOTAL_INPUT_BYTES:
        raise DataPrepError(f"入力合計が上限 {MAX_TOTAL_INPUT_BYTES} bytes を超えています")
    for path, limit in [
        (paths.postal_zip, MAX_POSTAL_ZIP_BYTES),
        (paths.stations_zip, MAX_STATION_ZIP_BYTES),
    ]:
        if path.stat().st_size > limit:
            raise DataPrepError(f"{path}: 容量上限 {limit} bytes を超えています")
    for code in ALL_PREFECTURE_CODES:
        path = paths.stat_mesh_csv(code)
        if path.stat().st_size > MAX_MESH_CSV_BYTES:
            raise DataPrepError(f"{path}: 容量上限 {MAX_MESH_CSV_BYTES} bytes を超えています")

    out = paths.national_out_dir
    destinations = [out / "postal.parquet", out / "muni_mesh.parquet", out / "stations.parquet"]
    existing = [path for path in destinations if path.exists()]
    if existing:
        raise DataPrepError(
            "出力が既にあります（上書きしません）: " + ", ".join(map(str, existing))
        )
    probe = out
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    if shutil.disk_usage(probe).free < MIN_OUTPUT_FREE_BYTES:
        raise DataPrepError(f"出力先の空き容量が {MIN_OUTPUT_FREE_BYTES} bytes 未満です: {probe}")

    with zipfile.ZipFile(paths.postal_zip) as archive:
        members = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(members) != 1:
            raise DataPrepError(f"{paths.postal_zip}: CSVが1つではありません: {members}")
        member = archive.getinfo(members[0])
        if member.file_size > MAX_POSTAL_MEMBER_BYTES:
            raise DataPrepError("郵便番号CSVの展開後サイズが上限を超えています")
        with archive.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig") as stream:
            postal_rows = postal.parse(
                (row for row in csv.reader(stream) if row),
                str(paths.postal_zip),
                pref_codes=ALL_PREFECTURE_CODES,
            )
    if len(postal_rows) > MAX_POSTAL_ROWS:
        raise DataPrepError(f"郵便番号の行数が上限 {MAX_POSTAL_ROWS} を超えています")

    mesh_rows: list[muni_mesh.MuniMesh] = []
    for code in ALL_PREFECTURE_CODES:
        mesh_rows.extend(
            muni_mesh.parse(
                _read_mesh_rows(paths.stat_mesh_csv(code)),
                str(paths.stat_mesh_csv(code)),
                pref_codes=(code,),
            )
        )
        if len(mesh_rows) > MAX_MESH_ROWS:
            raise DataPrepError(f"市区町村メッシュの行数が上限 {MAX_MESH_ROWS} を超えています")
    allowed = muni_mesh.meshes(mesh_rows)
    station_rows = _load_stations(paths, allowed)

    # Stage to exclusive temporary names. Each final output is published only
    # after all three tables have been written; existing files are never replaced.
    staged = [path.with_suffix(path.suffix + ".part") for path in destinations]
    if any(path.exists() for path in staged):
        raise DataPrepError("出力用一時ファイルが既にあります（上書きしません）")
    try:
        _write_batched(postal_rows, postal.SCHEMA, staged[0])
        _write_batched(mesh_rows, muni_mesh.SCHEMA, staged[1])
        _write_batched(station_rows, stations.SCHEMA, staged[2])
        out.mkdir(parents=True, exist_ok=True)
        for temp, destination in zip(staged, destinations, strict=True):
            temp.rename(destination)
    except Exception:
        # Keep any generated .part files for inspection; never delete data implicitly.
        raise
    return len(postal_rows), len(mesh_rows), len(station_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download", action="store_true", help="公式データを容量上限付きで取得する"
    )
    args = parser.parse_args()
    paths = Paths()
    try:
        if args.download:
            fetch(paths)
        counts = build(paths)
    except (DataPrepError, OSError, zipfile.BadZipFile, urllib.error.URLError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    print(f"{paths.national_out_dir} に全国Gazetteerを書き出しました")
    print(f"postal={counts[0]} muni_mesh={counts[1]} stations={counts[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
