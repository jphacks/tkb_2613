"""Import the national MLIT P05 2022 facility download into the POI index.

The official ``*_GML.zip`` is an outer archive of 47 prefecture ZIPs. Each
prefecture ZIP includes a GeoJSON FeatureCollection alongside its shapefile
assets; this importer reads one prefecture at a time and never extracts files.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import sqlite3
import tempfile
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow.parquet as pq

from tkb_data_prep.import_places import _import_features, _load_mesh_membership

DATASET = "P05-22"
VERSION = "2022"
PROVIDER = "国土交通省 国土数値情報"
LICENSE_ID = "PDL1.0"
ATTRIBUTION = (
    "出典：国土交通省国土数値情報「市町村役場等及び公的集会施設データ」"
    "（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05-v3_0.html）、"
    "PDL1.0（https://www.digital.go.jp/resources/open_data/public_data_license_v1.0）。"
    "P05_004（所在地）を除き、名称・施設分類・位置・行政区域コードを加工して作成。"
)
DEFAULT_OUTPUT = Path("data/processed/national/places.sqlite3")
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_FEATURE_BYTES = 1024 * 1024
MAX_INNER_ENTRIES = 64
PREFECTURES = tuple(f"{number:02d}" for number in range(1, 48))
CLASSIFICATIONS = {"1", "2", "3", "4", "5"}


class P05ArchiveError(ValueError):
    """The official P05 archive is unexpected or exceeds safe size limits."""


@dataclass(frozen=True)
class ImportResult:
    records: int
    prefectures: dict[str, int]
    classifications: dict[str, int]
    expanded_bytes: int
    output_bytes: int


@dataclass
class _ArchiveStats:
    classifications: Counter[str]
    expanded_bytes: int = 0

    @classmethod
    def create(cls) -> _ArchiveStats:
        return cls(Counter())


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and "\\" not in name
        and not name.startswith("/")
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _bounded_read(stream: Any, limit: int, description: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(64 * 1024, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise P05ArchiveError(f"{description} exceeds {limit} bytes")


def _municipality_names(mesh_index: Path) -> dict[str, str]:
    parquet = pq.ParquetFile(mesh_index)
    required = {"muni_code", "muni_name"}
    missing = required - set(parquet.schema_arrow.names)
    if missing:
        raise ValueError(f"mesh index is missing columns: {', '.join(sorted(missing))}")
    names: dict[str, set[str]] = {}
    for batch in parquet.iter_batches(columns=["muni_code", "muni_name"], batch_size=65536):
        for row in batch.to_pylist():
            code, name = row["muni_code"], row["muni_name"]
            if isinstance(code, str) and isinstance(name, str) and name.strip():
                names.setdefault(code.strip(), set()).add(name.strip())
    return {code: next(iter(values)) for code, values in names.items() if len(values) == 1}


def _features_for_prefecture(
    geojson_stream: Any,
    prefecture: str,
    municipalities: dict[str, str],
) -> Iterator[dict[str, Any]]:
    # A single prefecture FeatureCollection is bounded to 16 MiB before parsing;
    # the nationwide collection is never materialized.
    document = json.load(io.TextIOWrapper(geojson_stream, encoding="utf-8"))
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise P05ArchiveError(f"prefecture {prefecture}: expected GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list):
        raise P05ArchiveError(f"prefecture {prefecture}: missing features array")
    for ordinal, source in enumerate(features, start=1):
        if not isinstance(source, dict):
            raise P05ArchiveError(f"prefecture {prefecture}: invalid feature at row {ordinal}")
        feature_bytes = len(
            json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if feature_bytes > MAX_FEATURE_BYTES:
            raise P05ArchiveError(f"prefecture {prefecture}: a feature exceeds 1 MiB")
        properties = source.get("properties")
        geometry = source.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise P05ArchiveError(f"prefecture {prefecture}: invalid properties at row {ordinal}")
        municipality_code = str(properties.get("P05_001") or "").strip()
        classification = str(properties.get("P05_002") or "").strip()
        name = properties.get("P05_003")
        coordinates = geometry.get("coordinates")
        if (
            len(municipality_code) != 5
            or not municipality_code.isdigit()
            or municipality_code[:2] != prefecture
            or not classification
            or not isinstance(name, str)
            or not name.strip()
            or geometry.get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            raise P05ArchiveError(
                f"prefecture {prefecture}: required P05 fields invalid at row {ordinal}"
            )
        try:
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError) as error:
            raise P05ArchiveError(
                f"prefecture {prefecture}: invalid Point coordinates at row {ordinal}"
            ) from error
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise P05ArchiveError(f"prefecture {prefecture}: non-finite Point at row {ordinal}")
        locality = municipalities.get(municipality_code)
        addresses = [{"country": "JP"}]
        if locality:
            addresses[0]["locality"] = locality
        yield {
            "type": "Feature",
            "id": f"{DATASET}_{prefecture}_{ordinal:06d}",
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "properties": {
                "names": {"primary": name.strip()},
                "addresses": addresses,
                "basic_category": "public_facility",
                "taxonomy": {
                    "p05_classification_code": classification,
                    "p05_municipality_code": municipality_code,
                },
                "sources": [
                    {
                        "dataset": DATASET,
                        "provider": PROVIDER,
                        "license": LICENSE_ID,
                        "record_id": f"{DATASET}_{prefecture}_{ordinal:06d}",
                        "version": VERSION,
                        "source_url": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05-v3_0.html",
                    }
                ],
            },
        }


def _archive_features(
    archive_path: Path,
    municipalities: dict[str, str],
    stats: _ArchiveStats | None = None,
) -> Iterator[dict[str, Any]]:
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise P05ArchiveError(f"archive exceeds {MAX_ARCHIVE_BYTES} bytes")
    with zipfile.ZipFile(archive_path) as outer:
        entries = outer.infolist()
        expected = {f"P05-22_{prefecture}_GML.zip" for prefecture in PREFECTURES}
        if len(entries) != len(PREFECTURES) or {entry.filename for entry in entries} != expected:
            raise P05ArchiveError("outer archive must contain exactly the 47 prefecture ZIPs")
        if any(not _safe_member(entry.filename) for entry in entries):
            raise P05ArchiveError("outer archive contains an unsafe ZIP member path")
        if any(entry.file_size > MAX_ENTRY_BYTES for entry in entries):
            raise P05ArchiveError("a prefecture ZIP exceeds the per-entry size limit")

        expanded_total = 0
        for prefecture in PREFECTURES:
            nested_name = f"P05-22_{prefecture}_GML.zip"
            with outer.open(nested_name) as nested_stream:
                nested_bytes = _bounded_read(
                    nested_stream, MAX_ENTRY_BYTES, f"prefecture {prefecture} ZIP"
                )
            with zipfile.ZipFile(io.BytesIO(nested_bytes)) as inner:
                inner_entries = inner.infolist()
                if len(inner_entries) > MAX_INNER_ENTRIES:
                    raise P05ArchiveError(f"prefecture {prefecture}: too many ZIP entries")
                if any(not _safe_member(entry.filename) for entry in inner_entries):
                    raise P05ArchiveError(f"prefecture {prefecture}: unsafe ZIP member path")
                expanded_total += sum(entry.file_size for entry in inner_entries)
                if expanded_total > MAX_EXPANDED_BYTES:
                    raise P05ArchiveError("archive expanded contents exceed 128 MiB")
                if stats is not None:
                    stats.expanded_bytes = expanded_total
                if any(entry.file_size > MAX_ENTRY_BYTES for entry in inner_entries):
                    raise P05ArchiveError(f"prefecture {prefecture}: an entry exceeds 16 MiB")
                geojson_name = f"P05-22_{prefecture}.geojson"
                geojson = inner.getinfo(geojson_name) if geojson_name in inner.NameToInfo else None
                if geojson is None:
                    raise P05ArchiveError(f"prefecture {prefecture}: missing {geojson_name}")
                if geojson.file_size > MAX_ENTRY_BYTES:
                    raise P05ArchiveError(f"prefecture {prefecture}: GeoJSON exceeds 16 MiB")
                with inner.open(geojson) as geojson_stream:
                    geojson_bytes = _bounded_read(
                        geojson_stream, MAX_ENTRY_BYTES, f"prefecture {prefecture} GeoJSON"
                    )
                for feature in _features_for_prefecture(
                    io.BytesIO(geojson_bytes), prefecture, municipalities
                ):
                    if stats is not None:
                        code = feature["properties"]["taxonomy"]["p05_classification_code"]
                        stats.classifications[code] += 1
                    yield feature


def _inspect_archive(archive_path: Path) -> _ArchiveStats:
    """Preflight all 47 prefectures and report facility classification codes."""
    stats = _ArchiveStats.create()
    for _feature in _archive_features(archive_path, {}, stats):
        pass
    unknown = {
        code: count for code, count in stats.classifications.items() if code not in CLASSIFICATIONS
    }
    if unknown:
        raise P05ArchiveError(
            "unrecognized P05_002 classification counts (code only): "
            + json.dumps(unknown, sort_keys=True)
        )
    if not stats.classifications:
        raise P05ArchiveError("P05 archive contains no facility features")
    return stats


def import_p05(
    archive_path: Path,
    output_path: Path = DEFAULT_OUTPUT,
    *,
    mesh_index_path: Path = Path("data/processed/national/muni_mesh.parquet"),
) -> ImportResult:
    """Build a new P05 index atomically; existing indexes are never replaced."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing index: {output_path}")
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    allowed_meshes = _load_mesh_membership(mesh_index_path)
    municipalities = _municipality_names(mesh_index_path)
    stats = _inspect_archive(archive_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".p05-index-", dir=output_path.parent) as staging_dir:
        staged = Path(staging_dir) / "places.sqlite3"
        records = _import_features(
            _archive_features(archive_path, municipalities),
            staged,
            allowed_meshes,
            provider=PROVIDER,
            dataset=DATASET,
            version=VERSION,
            license_map={DATASET: LICENSE_ID},
            trusted_source_urls={
                DATASET: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05-v3_0.html"
            },
            attribution=ATTRIBUTION,
            country="JP",
            allow_country_missing=False,
        )
        if records == 0:
            raise P05ArchiveError("no P05 facilities passed the domestic mesh gate")
        if output_path.exists():
            raise FileExistsError(f"refusing to overwrite existing index: {output_path}")
        os.rename(staged, output_path)
    prefecture_counts: Counter[str] = Counter()
    with sqlite3.connect(output_path) as db:
        for pref in PREFECTURES:
            row = db.execute(
                "SELECT count(*) FROM poi_place WHERE place_id LIKE ?",
                (f"{DATASET}:{DATASET}_{pref}_%",),
            ).fetchone()
            prefecture_counts[pref] = int(row[0]) if row else 0
    return ImportResult(
        records,
        dict(prefecture_counts),
        dict(stats.classifications),
        stats.expanded_bytes,
        output_path.stat().st_size,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="official P05-22_GML.zip")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--mesh-index", type=Path, default=Path("data/processed/national/muni_mesh.parquet")
    )
    args = parser.parse_args()
    result = import_p05(args.input, args.output, mesh_index_path=args.mesh_index)
    covered = sum(count > 0 for count in result.prefectures.values())
    print(
        f"Imported {result.records} records; prefectures={covered}/47; "
        f"P05_002={result.classifications}; expanded_bytes={result.expanded_bytes}; "
        f"bytes={result.output_bytes}"
    )


if __name__ == "__main__":
    main()
