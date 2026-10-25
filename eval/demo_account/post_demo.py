"""デモ用アカウントに fixture の投稿をまとめて投稿する（tkb-2613.bsky.social など）。

fixture（eval/fixtures/demo_tama.json など）の posts を、古い順に1件ずつ投稿する。
写真つきの投稿は、--images のフォルダから「<画像のファイル名の頭>.jpg」を探して付ける
（fixture の画像 URL の最後の部分。demo_tama.json なら tama04.jpg、tama21.jpg など）。
写真は書き出し直して EXIF などのメタデータを落としてから送る。

ハンドル名とアプリパスワードは環境変数 BSKY_HANDLE と BSKY_APP_PASSWORD から読む
（ファイルに書かない）。
投稿する前に、プロフィールに「JPHACKS 2026 デモ用の架空アカウント」と書いておくこと。

  F=eval/fixtures/demo_tama.json
  uv run python eval/demo_account/post_demo.py $F --images ~/demo_photos --dry-run
  uv run python eval/demo_account/post_demo.py $F --images ~/demo_photos
  # 撮り直すときは、先に自分の投稿を全部消す（確認を求める）
  uv run python eval/demo_account/post_demo.py $F --images ~/demo_photos --delete-first
"""

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from atproto import Client
from PIL import Image, ImageOps

# 投稿の間隔（秒）。Bluesky の書き込みの上限に当たらないように少し空ける
INTERVAL_S = 2.0
# Bluesky に送る写真の長い辺と、ファイルの大きさの上限（1MB 未満）
MAX_SIDE_PX = 2000
MAX_BYTES = 950_000


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--images", type=Path, required=True, help="写真のフォルダ")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずに、投稿する内容を表示する")
    parser.add_argument("--delete-first", action="store_true", help="先に自分の投稿を全部消す")
    args = parser.parse_args()

    doc = json.loads(args.fixture.read_text(encoding="utf-8"))
    posts: list[dict[str, Any]] = sorted(doc["posts"], key=lambda p: p["created_at"])
    plan = [(p["text"], [_image_path(args.images, im["url"]) for im in p["images"]]) for p in posts]

    missing = [str(path) for _, paths in plan for path in paths if not path.is_file()]
    for n, (text, paths) in enumerate(plan, start=1):
        names = "、".join(p.name for p in paths)
        print(f"{n:>2}. {text}" + (f"  [写真: {names}]" if names else ""))
    if missing:
        print("\n写真が足りません:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    handle, password = os.environ.get("BSKY_HANDLE"), os.environ.get("BSKY_APP_PASSWORD")
    if not handle or not password:
        print("BSKY_HANDLE と BSKY_APP_PASSWORD を環境変数に入れてください", file=sys.stderr)
        return 1
    client = Client(base_url=os.environ.get("BSKY_SERVICE", "https://bsky.social") + "/xrpc")
    me = client.login(handle, password)
    if me is None:
        print("ログインできませんでした", file=sys.stderr)
        return 1

    if args.delete_first:
        _delete_all(client, me.did, handle)

    for n, (text, paths) in enumerate(plan, start=1):
        if paths:
            client.send_image(text=text, image=_clean_image(paths[0]), image_alt="")
        else:
            client.send_post(text=text)
        print(f"投稿しました {n}/{len(plan)}")
        time.sleep(INTERVAL_S)
    return 0


def _image_path(folder: Path, url: str) -> Path:
    stem = url.rsplit("/", 1)[-1].split("@", 1)[0]
    return folder / f"{stem}.jpg"


def _clean_image(path: Path) -> bytes:
    """向きを直して書き出し直す（EXIF などのメタデータは付けない）。大きければ縮める。"""
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    for quality in (90, 85, 80, 70, 60):
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=quality)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue()
    raise SystemExit(f"{path.name} が大きすぎます")


def _delete_all(client: Client, did: str, handle: str) -> None:
    uris: list[str] = []
    cursor = None
    while True:
        res = client.get_author_feed(actor=did, cursor=cursor, limit=100)
        uris += [item.post.uri for item in res.feed if item.post.author.did == did]
        cursor = res.cursor
        if not cursor:
            break
    answer = input(f"{handle} の投稿 {len(uris)} 件を消します。よければ yes と入力: ")
    if answer.strip() != "yes":
        raise SystemExit("やめました")
    for uri in uris:
        client.delete_post(uri)
    print(f"{len(uris)} 件消しました")


if __name__ == "__main__":
    sys.exit(main())
