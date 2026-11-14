"""実写真の手がかり抽出から居住地域の推論までを、段ごとに評価して切れ目を探す。

段：①観測（OCR・VLMが正解表の手がかりを読めたか）→ ②POI・駅の照合（候補が出て、正解が入るか）
→ ③一意性（status が candidate か）→ ④居住地域の経路（residential_area の候補が出たか）。

手がかりの取り方は2通り。
- ``--clues-file``：作ってある手がかりのJSONを読む（乾式。GPUも通信も使わない）
- ``--live``：detect を呼ぶ。VLM_BASE_URL / OCR_BASE_URL のチームのサーバーにだけ画像を送る

出力は標準出力のJSON（``--out`` でファイルにも書く）。ファイル名、post_id、
手がかりの type と value、
段ごとの判定だけを出し、画像バイト・投稿本文・キーは出さない。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "processed" / "national"
IMAGE_DIR_NAME = "images"
PLACE_TYPES = frozenset(
    {
        "station_sign",
        "shop",
        "landmark",
        "org_text",
        "place_text",
        "address_text",
        "postal_code",
        "rail_view",
    }
)
WILDCARD_TYPES = frozenset({"address_text", "postal_code", "phone"})
STAGES = ("observation", "poi_match", "uniqueness", "residential_area")
EXIT_UNREACHABLE = 2


def norm(value: str) -> str:
    """NFKC・大小文字・空白の差を無視した比較用の文字列。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def value_matches(predicted: str, truth: str, *, wildcard: bool = False) -> bool:
    """値の一致。完全一致か、短い側（3文字以上）が長い側に含まれる。wildcard なら x は任意1文字。"""
    p, t = norm(predicted), norm(truth)
    if not p or not t:
        return False
    if p == t:
        return True
    if wildcard and "x" in t:
        pattern = "".join("." if ch == "x" else re.escape(ch) for ch in t)
        if re.search(pattern, p):
            return True
    shorter, longer = (p, t) if len(p) <= len(t) else (t, p)
    return len(shorter) >= 3 and shorter in longer


def truth_matches(predicted: dict[str, Any], truth: dict[str, Any]) -> bool:
    wildcard = bool(truth.get("partial")) or truth["type"] in WILDCARD_TYPES
    return predicted["type"] == truth["type"] and value_matches(
        predicted["value"], truth["value"], wildcard=wildcard
    )


def loose_matches(predicted: dict[str, Any], truth: dict[str, Any]) -> bool:
    """type を問わず value だけで比べる（type の取り違えを見分ける参考値）。"""
    wildcard = bool(truth.get("partial")) or truth["type"] in WILDCARD_TYPES
    return value_matches(predicted["value"], truth["value"], wildcard=wildcard)


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def load_clue_rows(path: Path) -> list[dict[str, Any]]:
    """手がかりのJSON。{"clues": [...]} か、手がかりの配列のどちらも受け付ける。"""
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document.get("clues") if isinstance(document, dict) else document
    if not isinstance(rows, list):
        raise ValueError(
            "clues-file は手がかりの配列か、clues キーを持つオブジェクトにしてください"
        )
    return rows


async def live_clue_rows(posts_doc: dict[str, Any], image_dir: Path) -> list[dict[str, Any]]:
    """detect を実際に呼ぶ。接続できなければ ConnectionError。"""
    vlm_url = os.environ.get("VLM_BASE_URL", "").strip()
    ocr_url = os.environ.get("OCR_BASE_URL", "").strip()
    if not vlm_url or not ocr_url:
        raise ConnectionError(
            "--live には環境変数 VLM_BASE_URL と OCR_BASE_URL（GPUサーバー）が必要です。"
            "GPUを起動してから設定してください。"
        )
    from tkb_common.schemas import Post
    from tkb_detect.coords import COORDINATE_SPACE
    from tkb_detect.errors import DetectError
    from tkb_detect.extract import build_extractor

    extractor = build_extractor(
        mock_mode=False,
        vlm_base_url=vlm_url,
        vlm_api_key=os.environ.get("VLM_API_KEY", ""),
        vlm_model=os.environ.get("VLM_MODEL", ""),
        ocr_base_url=ocr_url,
        coordinate_space=COORDINATE_SPACE,
    )
    try:
        reachable = await extractor.model_reachable(10.0)
    except Exception as error:  # 接続失敗の詳細（URLやキー）は出さず種類だけ伝える
        raise ConnectionError(
            f"GPUサーバーに接続できません（{type(error).__name__}）。VLM/OCRの起動を確認してください。"
        ) from None
    if not reachable:
        raise ConnectionError(
            "VLM または OCR のサーバーが応答しません。GPUサーバーを起動し、"
            "VLM_BASE_URL / OCR_BASE_URL を確認してください。"
        )
    rows: list[dict[str, Any]] = []
    for raw in posts_doc["posts"]:
        if not raw.get("images"):
            continue
        files = [image.get("local_file") for image in raw["images"]]
        if any(not isinstance(f, str) or Path(f).name != f for f in files):
            raise ValueError("画像は local_file にファイル名だけを書いてください")
        post = Post.model_validate(
            {
                **raw,
                "images": [
                    {k: v for k, v in image.items() if k != "local_file"} for image in raw["images"]
                ],
            }
        )
        data = [(image_dir / str(f)).read_bytes() for f in files]
        try:
            clues = await extractor.extract_post(post, data)
        except DetectError as error:
            raise ConnectionError(f"手がかりの抽出に失敗しました: {error}") from None
        rows.extend(clue.model_dump(mode="json") for clue in clues)
    return rows


def evaluate(
    posts_doc: dict[str, Any],
    gt_doc: dict[str, Any],
    clue_rows: list[dict[str, Any]],
    data_dir: Path,
) -> dict[str, Any]:
    from tkb_common.schemas import Clue, PhotoPlaceResult, Post, ProfileAttribute
    from tkb_engine.cross_post import infer_owner_candidate_sets_with_web
    from tkb_engine.gazetteer import Gazetteer
    from tkb_engine.photo_place import infer_photo_places

    posts = [
        Post.model_validate(
            {
                **raw,
                "images": [
                    {k: v for k, v in image.items() if k != "local_file"} for image in raw["images"]
                ],
            }
        )
        for raw in posts_doc["posts"]
    ]
    clues = [Clue.model_validate(row) for row in clue_rows]
    gazetteer = Gazetteer.load(data_dir)
    owner_text = str(posts_doc.get("owner_profile_text", ""))

    def residential(results: Sequence[PhotoPlaceResult]) -> list[str]:
        sets = infer_owner_candidate_sets_with_web(
            posts,
            clues,
            [],
            owner_text,
            gazetteer=gazetteer,
            photo_place_results=results,
        )
        for item in sets:
            if item.attribute is ProfileAttribute.RESIDENTIAL_AREA:
                return [candidate.value for candidate in item.candidates]
        return []

    photo_results = infer_photo_places(posts, clues, gazetteer)
    results_by_image = {(r.post_id, r.image_index): r for r in photo_results}
    account_residential = residential(photo_results)
    baseline_residential = residential([])

    post_by_file: dict[str, Any] = {}
    for post, raw in zip(posts, posts_doc["posts"], strict=True):
        for image, raw_image in zip(post.images, raw["images"], strict=True):
            post_by_file[str(raw_image.get("local_file"))] = (post, image.index)

    clues_by_image: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for clue in clues:
        if clue.image_index is not None and clue.type.value in PLACE_TYPES:
            clues_by_image[(clue.post_id, clue.image_index)].append(
                {
                    "type": clue.type.value,
                    "value": clue.value,
                    "source": clue.source.value,
                }
            )

    rows: list[dict[str, Any]] = []
    obs_tp: dict[str, dict[str, int]] = defaultdict(
        lambda: {"truth": 0, "hit": 0, "pred": 0, "pred_hit": 0, "loose": 0}
    )
    by_source: dict[str, dict[str, int]] = defaultdict(
        lambda: {"truth": 0, "hit": 0, "pred": 0, "pred_hit": 0}
    )
    expected_images = 0
    counts = {
        "observation_ok": 0,
        "poi_candidate_returned": 0,
        "poi_correct": 0,
        "unique_correct": 0,
        "residential_contributed": 0,
        "abstain_images": 0,
        "abstain_ok": 0,
        "spurious_candidates": 0,
    }
    for entry in gt_doc["images"]:
        post, image_index = post_by_file[entry["file"]]
        key = (post.post_id, image_index)
        truths = entry["clues"]
        certain = [t for t in truths if not t.get("uncertain") and t["type"] in PLACE_TYPES]
        preds = clues_by_image.get(key, [])

        matched_truth = []
        for truth in certain:
            hit_sources = {p["source"] for p in preds if truth_matches(p, truth)}
            loose = any(loose_matches(p, truth) for p in preds)
            stat = obs_tp[truth["type"]]
            stat["truth"] += 1
            stat["hit"] += int(bool(hit_sources))
            stat["loose"] += int(loose)
            for source in ("ocr", "vlm"):
                by_source[source]["truth"] += 1
                by_source[source]["hit"] += int(source in hit_sources)
            matched_truth.append({**truth, "found": bool(hit_sources), "found_loose": loose})
        pred_rows = []
        for pred in preds:
            hit = any(truth_matches(pred, t) for t in truths)
            obs_tp[pred["type"]]["pred"] += 1
            obs_tp[pred["type"]]["pred_hit"] += int(hit)
            by_source[pred["source"]]["pred"] += 1
            by_source[pred["source"]]["pred_hit"] += int(hit)
            pred_rows.append({**pred, "in_truth": hit})
        observation_ok = all(t["found"] for t in matched_truth)

        result = results_by_image.get(key)
        status = result.status.value if result else "unknown"
        candidates = [c.label for c in result.candidates] if result else []
        names = entry["expected_place"]["names"]
        correct = bool(names) and any(
            value_matches(label, name)
            for label in [
                *candidates,
                *(c.area_label or "" for c in (result.candidates if result else [])),
            ]
            for name in names
        )
        contributed = False
        if names:
            without = [r for k, r in results_by_image.items() if k != key]
            contributed = bool(account_residential) and residential(without) != account_residential
            expected_images += 1
            counts["observation_ok"] += int(observation_ok)
            counts["poi_candidate_returned"] += int(bool(candidates))
            counts["poi_correct"] += int(correct)
            counts["unique_correct"] += int(correct and status == "candidate")
            counts["residential_contributed"] += int(contributed)
            stages = {
                "observation": observation_ok,
                "poi_match": correct,
                "uniqueness": correct and status == "candidate",
                "residential_area": contributed,
            }
            broken = next((s for s in STAGES if not stages[s]), "none")
        else:
            counts["abstain_images"] += 1
            counts["abstain_ok"] += int(not candidates)
            counts["spurious_candidates"] += int(bool(candidates))
            stages = {"observation": observation_ok}
            broken = "spurious_candidate" if candidates else "none"
        rows.append(
            {
                "file": entry["file"],
                "post_id": post.post_id,
                "expected_place": names[0] if names else None,
                "truth_clues": matched_truth,
                "predicted_clues": pred_rows,
                "stages": stages,
                "photo_place_status": status,
                "photo_place_candidates": candidates,
                "first_break": broken,
            }
        )

    break_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        break_counts[row["first_break"]] += 1
    return {
        "mode": "evaluation",
        "images": len(rows),
        "stage_summary": {
            "expected_place_images": expected_images,
            "abstain_expected_images": counts["abstain_images"],
            "1_observation": {
                "images_all_certain_clues_found": counts["observation_ok"],
                "by_type": {
                    t: {
                        "truth": s["truth"],
                        "recall": ratio(s["hit"], s["truth"]),
                        "recall_ignoring_type": ratio(s["loose"], s["truth"]),
                        "predicted": s["pred"],
                        "precision": ratio(s["pred_hit"], s["pred"]),
                    }
                    for t, s in sorted(obs_tp.items())
                },
                "by_source": {
                    s: {
                        "recall": ratio(v["hit"], v["truth"]),
                        "predicted": v["pred"],
                        "precision": ratio(v["pred_hit"], v["pred"]),
                    }
                    for s, v in sorted(by_source.items())
                    if s in {"ocr", "vlm"}
                },
            },
            "2_poi_match": {
                "candidate_returned": counts["poi_candidate_returned"],
                "correct_in_candidates": counts["poi_correct"],
                "denominator": expected_images,
            },
            "3_uniqueness": {
                "unique_and_correct": counts["unique_correct"],
                "denominator": expected_images,
                "abstain_images_with_no_candidate": counts["abstain_ok"],
                "abstain_images_with_spurious_candidate": counts["spurious_candidates"],
            },
            "4_residential_area": {
                "account_candidates": account_residential,
                "without_photo_places": baseline_residential,
                "images_contributing": counts["residential_contributed"],
                "denominator": expected_images,
            },
        },
        "first_break_counts": dict(sorted(break_counts.items(), key=lambda kv: -kv[1])),
        "per_image": rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posts", type=Path, required=True, help="demo_posts.json")
    parser.add_argument("--gt", type=Path, required=True, help="正解表 photo_place_gt.json")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--clues-file", type=Path, help="手がかりのJSON（乾式）")
    source.add_argument("--live", action="store_true", help="detect を実際に呼ぶ（GPUが必要）")
    parser.add_argument(
        "--images", type=Path, help="画像ディレクトリ（既定は posts と同じ場所の images）"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out", type=Path, help="結果JSONの出力先")
    args = parser.parse_args(argv)

    for path in (ROOT / "common" / "src", ROOT / "engine" / "src", ROOT / "detect" / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    posts_doc = json.loads(args.posts.read_text(encoding="utf-8"))
    gt_doc = json.loads(args.gt.read_text(encoding="utf-8"))
    if args.live:
        image_dir = args.images or args.posts.parent / IMAGE_DIR_NAME
        try:
            rows = asyncio.run(live_clue_rows(posts_doc, image_dir))
        except ConnectionError as error:
            print(f"接続できません: {error}", file=sys.stderr)
            return EXIT_UNREACHABLE
    else:
        if args.clues_file is None:
            parser.error("--clues-file か --live のどちらかを指定してください")
        rows = load_clue_rows(args.clues_file)
    report = evaluate(posts_doc, gt_doc, rows, args.data_dir)
    report["clue_source"] = "live" if args.live else "clues_file"
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
