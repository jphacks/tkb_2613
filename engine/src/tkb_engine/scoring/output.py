"""住まいの推定の結果を、API で返す形（tkb_common.residence）にする。"""

import math
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from tkb_common.residence import (
    ResidenceEstimate,
    ResidenceEvidence,
    ResidenceGeoprofile,
    ResidenceInfluence,
    ResidenceMap,
    ResidenceMapCell,
    ResidenceMapLabel,
    ResidenceRegion,
    ResidenceStep,
)
from tkb_engine.scoring.constants import (
    ASSUMPTIONS,
    CENSUS_SOURCE,
    MAP_HALF_WIDTH_M,
    MAP_LABELS,
    OSM_SOURCE,
)
from tkb_engine.scoring.estimate import (
    Estimate,
    Region,
    age_label,
    coverage_cells,
    describe_cell,
)
from tkb_engine.scoring.tables import ScoringTables

METERS_PER_DEG_LAT = 110_950.0
CELL_LAT = 3 / 3600
CELL_LON = 4.5 / 3600
SIGNIFICANT = 6
STATION_LABELS = 4


def _round(value: float) -> float:
    if value == 0 or not math.isfinite(value):
        return 0.0
    return round(value, SIGNIFICANT - 1 - math.floor(math.log10(abs(value))))


def region_model(tables: ScoringTables, region: Region) -> ResidenceRegion:
    described = describe_cell(tables, region.top_cell)
    minutes = described["station_walk_minutes"]
    return ResidenceRegion(
        people=_round(region.people),
        cells=region.cells,
        city=_str(described["city"]),
        town=_str(described["town"]),
        station=_str(described["station"]),
        station_walk_minutes=minutes if isinstance(minutes, int) else None,
        same_birthday=None if region.same_birthday is None else _round(region.same_birthday),
    )


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def residence_model(
    result: Estimate, tables: ScoringTables, clue_numbers: Sequence[int]
) -> ResidenceEstimate:
    """clue_numbers：推定に渡した手がかりの、診断の全手がかり（clues）での番号。"""
    geo = result.geoprofile
    with_geo = result.with_geoprofile
    return ResidenceEstimate(
        age_class=age_label(result.age),
        region=region_model(tables, result.region),
        geoprofile=(
            ResidenceGeoprofile(
                region=region_model(tables, with_geo[1]),
                places=[p.name for p in geo.places],
                other_bases=[p.name for p in geo.other_bases],
                buffer_m=round(geo.buffer_m, 1),
            )
            if geo is not None and with_geo is not None
            else None
        ),
        map=_map(result, tables),
        steps=[
            ResidenceStep(
                post_id=post_id,
                people=_round(region.people),
                cells=region.cells,
                same_birthday=(
                    None if region.same_birthday is None else _round(region.same_birthday)
                ),
            )
            for post_id, region in result.steps
        ],
        influence=sorted(
            (
                ResidenceInfluence(
                    post_id=post_id,
                    people_without=_round(region.people),
                    delta=_round(region.people - result.region.people),
                    contradiction=region.people < result.region.people,
                )
                for post_id, region in result.without.items()
            ),
            key=lambda i: -i.delta,
        ),
        evidence=[
            ResidenceEvidence(
                post_id=e.signal.post_id,
                layer=e.signal.layer,
                kind=e.signal.kind.value,
                value=e.signal.value,
                excerpt=e.signal.excerpt,
                applied=e.applied,
                clue_indices=[clue_numbers[i] for i in e.signal.clue_indices],
            )
            for e in result.evidence
        ],
        assumptions=list(ASSUMPTIONS),
        sources=[CENSUS_SOURCE, OSM_SOURCE],
    )


def _map(result: Estimate, tables: ScoringTables) -> ResidenceMap:
    top = result.region.top_cell
    lat0, lon0 = float(tables.lat[top]), float(tables.lon[top])
    half_lat = MAP_HALF_WIDTH_M / METERS_PER_DEG_LAT
    half_lon = half_lat / math.cos(math.radians(lat0))
    window = np.flatnonzero(
        (np.abs(tables.lat - lat0) <= half_lat) & (np.abs(tables.lon - lon0) <= half_lon)
    )
    in_region = np.zeros(tables.size, dtype=bool)
    in_region[coverage_cells(result.probability)] = True
    p_geo, geo = _geo(result, tables.size)
    cells = [
        ResidenceMapCell(
            lat=round(float(tables.lat[i]), 6),
            lon=round(float(tables.lon[i]), 6),
            p=_round(float(result.probability[i])),
            p_geo=_round(float(p_geo[i])),
            geo=min(1.0, max(0.0, round(float(geo[i]), 4))),
            in_region=bool(in_region[i]),
        )
        for i in window.tolist()
    ]
    return ResidenceMap(
        cell_lat=CELL_LAT,
        cell_lon=CELL_LON,
        cells=cells,
        labels=_labels(tables, top, half_lat, half_lon),
    )


def _geo(result: Estimate, size: int) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    if result.geoprofile is None or result.with_geoprofile is None:
        return result.probability, np.zeros(size, dtype=np.float64)
    return result.with_geoprofile[0], result.geoprofile.weights


def _labels(
    tables: ScoringTables, top: int, half_lat: float, half_lon: float
) -> list[ResidenceMapLabel]:
    lat0, lon0 = float(tables.lat[top]), float(tables.lon[top])
    stations: dict[str, tuple[float, float, float]] = {}
    for name, lat, lon in zip(
        tables.stations.name, tables.stations.lat, tables.stations.lon, strict=True
    ):
        if abs(lat - lat0) <= half_lat and abs(lon - lon0) <= half_lon:
            d = math.hypot(lat - lat0, (lon - lon0) * math.cos(math.radians(lat0)))
            if name not in stations or d < stations[name][2]:
                stations[name] = (float(lat), float(lon), d)
    labels = [
        ResidenceMapLabel(kind="station", name=name, lat=round(a, 6), lon=round(b, 6))
        for name, (a, b, _) in sorted(stations.items(), key=lambda kv: kv[1][2])[:STATION_LABELS]
    ]
    town = int(tables.town[top])
    if town >= 0:
        labels.append(
            ResidenceMapLabel(
                kind="town",
                name=tables.towns.name[town],
                lat=round(float(tables.towns.lat[town]), 6),
                lon=round(float(tables.towns.lon[town]), 6),
            )
        )
    return labels[:MAP_LABELS]
