"""デモ投稿を指定アカウントへ追加する。パスワードは入力時だけメモリに置く。

既定は X1 の投稿案（x1_posts.json）。X2〜X5 の投稿案は --plan chain_posts.json。
"""

import argparse
import getpass
import json
import time
from pathlib import Path

from atproto import Client

PLAN = Path(__file__).with_name("x1_posts.json")
INTERVAL_SECONDS = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Bluesky に実際に投稿する")
    parser.add_argument(
        "--plan", default=PLAN.name, help="投稿案のファイル名（このスクリプトと同じフォルダ）"
    )
    args = parser.parse_args()
    plan = json.loads(PLAN.with_name(args.plan).read_text(encoding="utf-8"))
    handle: str = plan["handle"]
    texts: list[str] = [post["text"] for post in plan["posts"]]
    for number, text in enumerate(texts, 1):
        print(f"{number}. {text}")
    if not args.publish:
        return 0

    password = getpass.getpass("Bluesky アプリパスワード: ")
    client = Client()
    me = client.login(handle, password)
    del password
    profile = client.get_profile(handle)
    if me.did != profile.did:
        raise SystemExit("ログインした DID が投稿先と一致しません")

    notice: str = plan["profile_notice"]
    if notice not in (profile.description or ""):
        current = client.com.atproto.repo.get_record(
            {"repo": me.did, "collection": "app.bsky.actor.profile", "rkey": "self"}
        )
        # SDK が付けた省略可能フィールドの null は Lexicon の検証に通らない。
        record = {key: value for key, value in dict(current.value).items() if value is not None}
        description = str(record.get("description") or "").strip()
        record["description"] = f"{description}\n{notice}".strip()
        client.com.atproto.repo.put_record(
            {
                "repo": me.did,
                "collection": "app.bsky.actor.profile",
                "rkey": "self",
                "record": record,
                "swap_record": current.cid,
            }
        )
        print("デモ用プロフィール表記を追加しました")

    existing = {
        item.post.record.text
        for item in client.get_author_feed(actor=me.did, limit=100).feed
        if item.post.author.did == me.did
    }
    for text in texts:
        if text in existing:
            print("既存の同文投稿を確認したためスキップしました")
            continue
        result = client.send_post(text=text)
        print(f"投稿しました: {result.uri}")
        time.sleep(INTERVAL_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
