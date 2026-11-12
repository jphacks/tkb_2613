"""対象の都県と、ファイルの置き場所。"""

from dataclasses import dataclass
from pathlib import Path

# 1都3県（埼玉・千葉・東京・神奈川）
PREFECTURES: dict[str, str] = {
    "11": "埼玉県",
    "12": "千葉県",
    "13": "東京都",
    "14": "神奈川県",
}

DATA_PREP_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = DATA_PREP_DIR.parent


@dataclass(frozen=True)
class Paths:
    raw_dir: Path = DATA_PREP_DIR / "raw"
    manual_dir: Path = DATA_PREP_DIR / "manual"
    out_dir: Path = REPO_ROOT / "data" / "processed"

    @property
    def postal_zip(self) -> Path:
        return self.raw_dir / "japanpost" / "utf_ken_all.zip"

    def stat_mesh_csv(self, pref_code: str) -> Path:
        return self.raw_dir / "stat_mesh" / f"{pref_code}.csv"

    @property
    def stations_zip(self) -> Path:
        return self.raw_dir / "ksj" / "N02-24_GML.zip"

    def ksj_bus_stop_zip(self, pref_code: str) -> Path:
        """国土数値情報「バス停留所（P11）」令和4年度版の都道府県ごとの zip。"""
        return self.raw_dir / "ksj" / f"P11-22_{pref_code}_SHP.zip"

    def ksj_boundary_zip(self, pref_code: str) -> Path:
        """国土数値情報「行政区域（N03）」2026年1月1日時点の都道府県ごとの zip。"""
        return self.raw_dir / "ksj" / f"N03-20260101_{pref_code}_GML.zip"

    def ksj_school_district_zip(self, prefix: str, pref_code: str) -> Path:
        """国土数値情報「小学校区（A27）」「中学校区（A32）」令和3年度版の都道府県ごとの zip。"""
        return self.raw_dir / "ksj" / f"{prefix}-21_{pref_code}_GML.zip"

    @property
    def ksj_school_terms_xlsx(self) -> Path:
        """小学校区・中学校区の、自治体ごとの利用条件の一覧。"""
        return self.raw_dir / "ksj" / "R3_Terms_of_use_municipality_data.xlsx"

    @property
    def estat_dir(self) -> Path:
        return self.raw_dir / "estat"

    @property
    def mext_dir(self) -> Path:
        return self.raw_dir / "mext"

    @property
    def houjin_dir(self) -> Path:
        """法人番号公表サイトの全件データ（ブラウザで取得して手で置く）。"""
        return self.raw_dir / "houjin"

    @property
    def gsi_dir(self) -> Path:
        return self.raw_dir / "gsi"

    @property
    def area_codes_csv(self) -> Path:
        return self.manual_dir / "area_codes.csv"
