"""Stream local GeoJSONL place records into an optional SQLite exact-name index."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from shapely import wkb
from shapely.errors import GEOSException

from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION, place_name_keys

DEFAULT_OUTPUT = Path("data/processed/places.sqlite3")


def _features(path: Path) -> Iterator[dict[str, Any]]:
    """Read one GeoJSON Feature per line; never materialize the national input."""
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                feature = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid GeoJSONL at line {line_number}") from error
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise ValueError(f"expected one GeoJSON Feature per line (line {line_number})")
            yield feature


_PRIVATE_CATEGORIES = {
    "home",
    "house",
    "private_house",
    "private_residence",
    "residence",
    "residential_building",
    "residential",
    "apartment",
    "apartments",
    "dwelling",
}


def _is_private(properties: dict[str, Any]) -> bool:
    values: set[str] = set()
    basic = properties.get("basic_category")
    if isinstance(basic, str):
        values.add(basic.casefold().replace("-", "_").replace(" ", "_"))
    def collect_categories(value: Any) -> None:
        if isinstance(value, str):
            values.add(value.casefold().replace("-", "_").replace(" ", "_"))
        elif isinstance(value, dict):
            for child in value.values():
                collect_categories(child)
        elif isinstance(value, list):
            for child in value:
                collect_categories(child)

    collect_categories(properties.get("taxonomy"))
    return bool(values & _PRIVATE_CATEGORIES)


def _geoparquet_features(path: Path, *, batch_size: int) -> Iterator[dict[str, Any]]:
    """Read prepared Overture Places GeoParquet in bounded Arrow batches.

    Inputs must retain Overture's theme/type partition columns so address points
    and non-Places rows cannot accidentally enter this index.
    """
    parquet = pq.ParquetFile(path)
    required = {"id", "theme", "type", "geometry", "names", "addresses", "sources"}
    missing = required - set(parquet.schema_arrow.names)
    if missing:
        raise ValueError(f"GeoParquet missing required columns: {', '.join(sorted(missing))}")
    selected = sorted(required) + [
        column for column in ("basic_category", "taxonomy") if column in parquet.schema_arrow.names
    ]
    for batch in parquet.iter_batches(batch_size=batch_size, columns=selected):
        for row in batch.to_pylist():
            if row.get("theme") != "places" or row.get("type") != "place":
                continue
            geometry_value = row.get("geometry")
            if geometry_value is None:
                continue
            try:
                geometry = wkb.loads(geometry_value)
            except (TypeError, ValueError, GEOSException):
                continue
            properties = {
                key: value
                for key, value in row.items()
                if key not in {"id", "theme", "type", "geometry", "bbox"}
            }
            if _is_private(properties):
                continue
            yield {
                "type": "Feature",
                "id": row.get("id"),
                "geometry": {
                    "type": geometry.geom_type,
                    "coordinates": list(geometry.coords[0])
                    if geometry.geom_type == "Point"
                    else [],
                },
                "properties": properties,
            }


def _area_label(addresses: Any, *, country: str) -> str | None:
    """Keep an explicit municipality-shaped locality, never parse freeform text."""
    if not isinstance(addresses, list):
        return None
    localities = {
        str(address.get("locality")).strip()
        for address in addresses
        if isinstance(address, dict)
        and str(address.get("country", "")).upper() == country.upper()
        and isinstance(address.get("locality"), str)
        and address["locality"].strip()
        and address["locality"].strip().endswith(("市", "区", "町", "村"))
    }
    return next(iter(localities)) if len(localities) == 1 else None


def _names(properties: dict[str, Any]) -> tuple[str, list[str]]:
    names = properties.get("names", {})
    if not isinstance(names, dict):
        names = {}
    primary = str(names.get("primary") or properties.get("name") or "").strip()
    aliases: set[str] = set()
    common = names.get("common", {})
    if isinstance(common, dict):
        for values in common.values():
            if isinstance(values, str):
                aliases.add(values.strip())
            elif isinstance(values, list):
                aliases.update(str(value).strip() for value in values if str(value).strip())
    rules = names.get("rules", [])
    if isinstance(rules, list):
        aliases.update(
            str(rule["value"]).strip()
            for rule in rules
            if isinstance(rule, dict) and rule.get("value")
        )
    legacy = properties.get("aliases", [])
    if isinstance(legacy, list):
        aliases.update(str(value).strip() for value in legacy if str(value).strip())
    aliases.discard(primary)
    return primary, sorted(alias for alias in aliases if alias)


def _source_records(
    raw_sources: Any,
    *,
    place_id: str,
    provider: str,
    dataset: str,
    license_map: dict[str, str],
    version: str | None,
    attribution: str | None,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if isinstance(raw_sources, list):
        for source in raw_sources:
            if not isinstance(source, dict):
                continue
            source_dataset = str(source.get("dataset") or dataset)
            record_id = source.get("record_id") or place_id
            sources.append(
                {
                    "source_id": f"{source_dataset}:{record_id}",
                    "provider": str(source.get("provider") or provider),
                    "dataset": source_dataset,
                    "license_id": source.get("license") or license_map.get(source_dataset),
                    "record_id": str(record_id),
                    "version": str(source.get("version") or version)
                    if source.get("version") or version
                    else None,
                    "attribution": attribution,
                }
            )
    if not sources:
        sources.append(
            {
                "source_id": f"{dataset}:{place_id}",
                "provider": provider,
                "dataset": dataset,
                "license_id": license_map.get(dataset),
                "record_id": place_id,
                "version": version,
                "attribution": attribution,
            }
        )
    return sources


def _import_features(
    features: Iterator[dict[str, Any]],
    output_path: Path,
    *,
    provider: str,
    dataset: str,
    version: str | None = None,
    license_map: dict[str, str] | None = None,
    attribution: str | None = None,
    country: str = "JP",
    allow_country_missing: bool = False,
    batch_size: int = 1000,
) -> int:
    """Build a stable-ID place/alias index with bounded memory use."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing index: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output_path) as db:
        db.execute(f"PRAGMA user_version = {PLACE_INDEX_SCHEMA_VERSION}")
        db.executescript(
            """
            CREATE TABLE poi_place (
                place_id TEXT PRIMARY KEY,
                license_verified INTEGER NOT NULL,
                record_json TEXT NOT NULL
            );
            """
            """
            CREATE TABLE poi_alias (
                name_key TEXT NOT NULL,
                place_id TEXT NOT NULL,
                PRIMARY KEY(name_key, place_id),
                FOREIGN KEY(place_id) REFERENCES poi_place(place_id)
            );
            """
            "CREATE INDEX poi_alias_name_idx ON poi_alias(name_key);"
        )
        count = 0
        for feature in features:
            properties = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                continue
            addresses = properties.get("addresses", [])
            countries = (
                {
                    str(address.get("country", "")).upper()
                    for address in addresses
                    if isinstance(address, dict) and address.get("country")
                }
                if isinstance(addresses, list)
                else set()
            )
            if countries and country.upper() not in countries:
                continue
            if not countries and not allow_country_missing:
                continue
            coordinates = geometry.get("coordinates", [])
            if (
                geometry.get("type") != "Point"
                or not isinstance(coordinates, list)
                or len(coordinates) < 2
            ):
                continue
            try:
                longitude, latitude = float(coordinates[0]), float(coordinates[1])
            except (TypeError, ValueError):
                continue
            if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                continue
            raw_id = feature.get("id") or properties.get("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                continue
            provider_id = raw_id.strip()
            place_id = f"{dataset}:{provider_id}"
            label, aliases = _names(properties)
            if not label:
                continue
            sources = _source_records(
                properties.get("sources"),
                place_id=provider_id,
                provider=provider,
                dataset=dataset,
                license_map=license_map or {},
                version=version,
                attribution=attribution,
            )
            record = {
                "place_id": place_id,
                "label": label,
                "aliases": aliases,
                "longitude": longitude,
                "latitude": latitude,
                "country": country.upper(),
                "area_label": _area_label(addresses, country=country),
                "basic_category": properties.get("basic_category"),
                "taxonomy": properties.get("taxonomy"),
                "sources": sources,
            }
            license_verified = int(
                bool(sources) and all(source.get("license_id") for source in sources)
            )
            db.execute(
                "INSERT OR IGNORE INTO poi_place"
                "(place_id, license_verified, record_json) VALUES (?, ?, ?)",
                (
                    place_id,
                    license_verified,
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            if license_verified:
                db.executemany(
                    "INSERT OR IGNORE INTO poi_alias(name_key, place_id) VALUES (?, ?)",
                    (
                        (key, place_id)
                        for name in (label, *aliases)
                        for key in place_name_keys(name)
                    ),
                )
            count += 1
            if count % batch_size == 0:
                db.commit()
        db.commit()
        return count


def import_geojsonl(
    input_path: Path,
    output_path: Path,
    *,
    provider: str,
    dataset: str,
    version: str | None = None,
    license_map: dict[str, str] | None = None,
    attribution: str | None = None,
    country: str = "JP",
    allow_country_missing: bool = False,
    batch_size: int = 1000,
) -> int:
    """Import local GeoJSONL using the shared bounded SQLite writer."""
    return _import_features(
        _features(input_path),
        output_path,
        provider=provider,
        dataset=dataset,
        version=version,
        license_map=license_map,
        attribution=attribution,
        country=country,
        allow_country_missing=allow_country_missing,
        batch_size=batch_size,
    )


def import_geoparquet(
    input_path: Path,
    output_path: Path,
    *,
    provider: str,
    dataset: str,
    version: str | None = None,
    license_map: dict[str, str] | None = None,
    attribution: str | None = None,
    country: str = "JP",
    allow_country_missing: bool = False,
    batch_size: int = 1000,
) -> int:
    """Import prepared Overture Places GeoParquet without a GeoJSONL copy."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    features = _geoparquet_features(input_path, batch_size=batch_size)
    return _import_features(
        features,
        output_path,
        provider=provider,
        dataset=dataset,
        version=version,
        license_map=license_map,
        attribution=attribution,
        country=country,
        allow_country_missing=allow_country_missing,
        batch_size=batch_size,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="local GeoJSONL or GeoParquet")
    parser.add_argument(
        "--input-format",
        choices=("geojsonl", "geoparquet"),
        default="geojsonl",
        help="prepared Overture Places GeoParquet requires theme/type partition columns",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"API既定gazetteerのSQLite索引 ({DEFAULT_OUTPUT})",
    )
    parser.add_argument("--provider", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--version")
    parser.add_argument(
        "--source-license-map",
        type=Path,
        help="JSON mapping source dataset names to verified SPDX IDs",
    )
    parser.add_argument("--attribution")
    parser.add_argument("--country", default="JP")
    parser.add_argument(
        "--allow-country-missing",
        action="store_true",
        help="only for inputs already clipped to the requested country",
    )
    args = parser.parse_args()
    license_map = (
        json.loads(args.source_license_map.read_text(encoding="utf-8"))
        if args.source_license_map
        else {}
    )
    if not isinstance(license_map, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in license_map.items()
    ):
        parser.error("--source-license-map must be a JSON object of dataset name to SPDX ID")
    importer = import_geoparquet if args.input_format == "geoparquet" else import_geojsonl
    count = importer(
        args.input,
        args.output,
        provider=args.provider,
        dataset=args.dataset,
        version=args.version,
        license_map=license_map,
        attribution=args.attribution,
        country=args.country,
        allow_country_missing=args.allow_country_missing,
    )
    print(f"Imported {count} POI records")


if __name__ == "__main__":
    main()
