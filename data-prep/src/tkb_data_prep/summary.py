"""変換の最後に表示する件数（妥当かを人が確かめるためのもの）。"""

from dataclasses import dataclass

from tkb_data_prep.area_codes import AreaCode, Problem
from tkb_data_prep.bus_stops import BusStop
from tkb_data_prep.corporations import BuildResult
from tkb_data_prep.households import Household
from tkb_data_prep.muni_mesh import MuniMesh
from tkb_data_prep.postal import Postal
from tkb_data_prep.school_districts import District
from tkb_data_prep.schools import School
from tkb_data_prep.shelters import Shelter
from tkb_data_prep.stations import Station


@dataclass(frozen=True)
class Tables:
    muni_mesh: list[MuniMesh]
    households: list[Household]
    estat_first_meshes: frozenset[str]
    postal: list[Postal]
    stations: list[Station]
    area_codes: list[AreaCode]
    area_code_problems: list[Problem]
    schools: list[School]
    shelters: list[Shelter]
    school_districts: list[District]
    bus_stops: list[BusStop]
    corporations: BuildResult


def report(t: Tables) -> list[str]:
    meshes_1km = {m.mesh_1km for m in t.muni_mesh}
    with_households = {h.mesh_1km for h in t.households}
    missing_first = " ".join(sorted({m[:4] for m in meshes_1km} - t.estat_first_meshes))
    munis = len({m.muni_code for m in t.muni_mesh})
    lines = [
        "== 行数 ==",
        f"muni_mesh        {len(t.muni_mesh):>9,} 行"
        f"（市区町村 {munis:,}、1km メッシュ {len(meshes_1km):,}）",
        f"households_500m  {len(t.households):>9,} 行",
        f"postal           {len(t.postal):>9,} 行"
        f"（郵便番号 {len({p.postal_code for p in t.postal}):,}）",
        f"stations         {len(t.stations):>9,} 行"
        f"（駅名 {len({s.station_name for s in t.stations}):,}）",
        f"area_codes       {len(t.area_codes):>9,} 行"
        f"（うち一部だけが対象 {sum(a.partial for a in t.area_codes):,}）",
        f"schools          {len(t.schools):>9,} 行"
        f"（市区町村が引けない {sum(not s.city for s in t.schools):,}）",
        f"shelters         {len(t.shelters):>9,} 行"
        f"（2つ以上の区市町村にある名前 {_shared_names(t.shelters):,}）",
        f"bus_stops        {len(t.bus_stops):>9,} 行"
        f"（2つ以上の区市町村にかかる {sum(len(b.cities) > 1 for b in t.bus_stops):,}）",
        f"school_districts {len(t.school_districts):>9,} 行"
        f"（取り込んだ自治体 {len({d.muni_code for d in t.school_districts}):,}）",
        _corporations_line(t.corporations),
        "",
        "== 世帯数 ==",
        f"世帯数の合計 {sum(h.households for h in t.households):,}",
        f"人口の合計   {sum(h.population for h in t.households):,}",
        f"世帯数の行がない 1km メッシュ {len(meshes_1km - with_households):,}"
        f" / {len(meshes_1km):,}",
        f"e-Stat の zip がない第1次地域区画: {missing_first or 'なし'}",
        "",
        f"== 市外局番：市区町村コードに直せなかったもの {len(t.area_code_problems)} 件 ==",
    ]
    lines += [
        f"{p.area_code}（番号区画 {p.section_code}）{p.text}: {p.reason}"
        for p in t.area_code_problems
    ]
    return lines


def _shared_names(rows: list[Shelter]) -> int:
    munis: dict[str, set[str]] = {}
    for r in rows:
        munis.setdefault(r.name, set()).add(r.muni_code)
    return sum(len(m) > 1 for m in munis.values())


def _corporations_line(result: BuildResult) -> str:
    if not result.rows:
        return "corporations     作っていません（raw/houjin/ に法人番号の zip がない）"
    return f"corporations     {result.rows:>9,} 行（{result.as_of} 時点、SQLite）"
