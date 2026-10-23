"""変換の最後に表示する件数（妥当かを人が確かめるためのもの）。"""

from dataclasses import dataclass

from tkb_data_prep.area_codes import AreaCode, Problem
from tkb_data_prep.households import Household
from tkb_data_prep.muni_mesh import MuniMesh
from tkb_data_prep.postal import Postal
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
