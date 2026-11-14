"""Stream local GeoJSONL place records into an optional SQLite exact-name index."""

from __future__ import annotations

import argparse
import json
import sqlite3
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT = Path("data/processed/places.sqlite3")


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in value if character.isalnum())


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
    """Build a stable-ID place/alias index with bounded memory use."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing index: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output_path) as db:
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
        for feature in _features(input_path):
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
                    ((key, place_id) for name in (label, *aliases) if (key := _normalized(name))),
                )
            count += 1
            if count % batch_size == 0:
                db.commit()
        db.commit()
        return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="local newline-delimited GeoJSON Features"
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
    count = import_geojsonl(
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
