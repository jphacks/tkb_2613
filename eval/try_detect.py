"""手元の画像と本文から手がかりを取り出して表示する（試し用）。

使い方：
    uv run python eval/try_detect.py eval/photos/a.jpg --text "夜勤明けのラーメン"
    uv run python eval/try_detect.py --text "25歳になりました"

接続先はリポジトリのルートの .env（MOCK_MODE、VLM_*、OCR_BASE_URL）から読む。
写真はチームの vLLM と OCR にだけ送る（detect の guard を通る）。写真はコミットしない。
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from tkb_common.schemas import Post
from tkb_detect.coords import COORDINATE_SPACE, CoordinateSpace
from tkb_detect.errors import DetectError
from tkb_detect.extract import build_extractor

ROOT = Path(__file__).resolve().parents[1]
TRY_POST_ID = "at://did:plc:try/app.bsky.feed.post/try"
TRUE_VALUES = {"1", "true", "yes", "on"}


def load_dotenv(path: Path) -> None:
    """KEY=VALUE の行だけを読む。すでに環境変数にあるものは上書きしない。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def build_post(paths: list[Path], text: str) -> tuple[Post, list[bytes]]:
    images, metas = [], []
    for i, path in enumerate(paths):
        data = path.read_bytes()
        with Image.open(path) as image:
            width, height = image.size
        images.append(data)
        metas.append(
            {
                "index": i,
                "url": f"https://cdn.bsky.app/try/{i}",
                "alt": "",
                "width": width,
                "height": height,
            }
        )
    post = Post(
        post_id=TRY_POST_ID,
        text=text,
        created_at=datetime.now(UTC),
        images=metas,  # type: ignore[arg-type]
    )
    return post, images


async def run(args: argparse.Namespace) -> int:
    load_dotenv(ROOT / ".env")
    mock_mode = os.environ.get("MOCK_MODE", "1").lower() in TRUE_VALUES
    extractor = build_extractor(
        mock_mode=mock_mode,
        vlm_base_url=os.environ.get("VLM_BASE_URL", ""),
        vlm_api_key=os.environ.get("VLM_API_KEY", ""),
        vlm_model=os.environ.get("VLM_MODEL", ""),
        ocr_base_url=os.environ.get("OCR_BASE_URL", ""),
        coordinate_space=CoordinateSpace(args.space) if args.space else COORDINATE_SPACE,
    )

    post, images = build_post(args.images, args.text)
    try:
        clues = await extractor.extract_post(post, images)
    except DetectError as e:
        print(f"失敗しました: {e}", file=sys.stderr)
        return 1

    ocr = "あり" if extractor.uses_ocr else "なし"
    print(f"MOCK_MODE={int(mock_mode)} OCR={ocr}", file=sys.stderr)
    print(json.dumps([c.model_dump(mode="json") for c in clues], ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="画像と本文から手がかりを取り出して表示する")
    parser.add_argument("images", nargs="*", type=Path, help="画像のパス（4枚まで）")
    parser.add_argument("--text", default="", help="投稿の本文")
    parser.add_argument(
        "--space",
        choices=[s.value for s in CoordinateSpace],
        help="座標の単位を一時的に指定する（確認用）",
    )
    args = parser.parse_args()
    if not args.images and not args.text:
        parser.error("画像のパスか --text のどちらかを指定してください")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
