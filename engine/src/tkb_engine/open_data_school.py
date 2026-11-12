"""子どもの学校の推定（child_school）から、国土数値情報の学区で居住地域の経路を足す。

公立の小学校・中学校は、通学区域（学区）に住む子が通う。子どもの学校の推定が出ていて、
その学校の学区がわかるときだけ、学区の区市町村を居住地域の経路に足す。
- 子どもの学校の推定がないときは何もしない（制服や校舎の写真だけから学区を引かない）
- 同じ名前の学校が2つ以上の区市町村にあるときは使わない
- 既にある居住地域の推定と区市町村が違うときは、どちらも捨てる
- 学区の境界には推定が含まれ、公式な資料ではない。根拠にそう書き、自治体の条件があれば添える
"""

from tkb_common.schemas import (
    ClaimAssessment,
    EvidenceScope,
    ProfileAttribute,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileItem,
    ProfileStatus,
)
from tkb_engine.gazetteer import Gazetteer

OPEN_DATA_CONFIDENCE = 0.9
FOUND_CONFIDENCE = 0.8


def add_school_district_residence(
    claims: list[ProfileItem], gazetteer: Gazetteer
) -> list[ProfileItem]:
    """claims に、学区からの居住地域の経路を足したもの。足せなければ claims のまま。"""
    school = next(
        (
            c
            for c in claims
            if c.attribute is ProfileAttribute.CHILD_SCHOOL
            and c.status is not ProfileStatus.UNKNOWN
            and c.value
            and c.evidence_paths
        ),
        None,
    )
    if school is None or school.value is None:
        return claims
    districts = gazetteer.districts_of_school(school.value)
    cities = {str(d["city"]) for d in districts}
    if len(cities) != 1:
        return claims
    city = next(iter(cities))
    cited = ProfileEvidence(
        required=True, source="open_data", excerpt=_citation(school.value, city, districts)
    )
    paths = [
        ProfileEvidencePath(
            evidence=[*path.evidence, cited],
            confidence=min(path.confidence, OPEN_DATA_CONFIDENCE),
        )
        for path in school.evidence_paths
    ]
    current = next((c for c in claims if c.attribute is ProfileAttribute.RESIDENTIAL_AREA), None)
    if current is not None and current.value != city:
        return [c for c in claims if c is not current]
    all_paths = [*(current.evidence_paths if current else []), *paths]
    confidence = max(p.confidence for p in all_paths)
    residence = ProfileItem(
        attribute=ProfileAttribute.RESIDENTIAL_AREA,
        value=city,
        confidence=confidence,
        status=ProfileStatus.FOUND if confidence >= FOUND_CONFIDENCE else ProfileStatus.WEAK,
        evidence=[ref for path in all_paths for ref in path.evidence],
        evidence_paths=all_paths,
        assessment=(
            current.assessment if current else ClaimAssessment(minimal_scope=EvidenceScope.BLUESKY)
        ),
    )
    return [c for c in claims if c is not current] + [residence]


def _citation(school: str, city: str, districts: list[dict[str, object]]) -> str:
    kinds = sorted({str(d.get("kind") or "") for d in districts}, reverse=True)
    sources = "・".join(f"「国土数値情報（{k}区データ）」" for k in kinds if k)
    notes = sorted({str(d.get("note") or "") for d in districts if d.get("note")})
    condition = "".join(f"。{city}の条件：{note}" for note in notes)
    return (
        f"{school}の通学区域は{city}（出典：{sources}（国土交通省）を加工して作成。"
        f"令和3年度のデータで、境界には推定が含まれ、公式な資料ではありません{condition}）"
    )
