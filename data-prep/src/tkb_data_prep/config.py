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

    @property
    def estat_dir(self) -> Path:
        return self.raw_dir / "estat"

    @property
    def mext_dir(self) -> Path:
        return self.raw_dir / "mext"

    @property
    def area_codes_csv(self) -> Path:
        return self.manual_dir / "area_codes.csv"
