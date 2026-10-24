"""MOCK_MODE で返す固定の手がかり。架空のデモ用アカウントの投稿のもの。"""

from tkb_api.schemas import Clue, ClueSource, ClueType, DetectResponse

MOCK_POST_ID = "at://did:plc:demo0000000000000000000/app.bsky.feed.post/3demo000001"

MOCK_RESPONSE = DetectResponse(
    clues=[
        Clue(
            post_id=MOCK_POST_ID,
            image_index=0,
            type=ClueType.STATION_SIGN,
            value="新宿",
            region=(120, 80, 340, 150),
            confidence=0.92,
            source=ClueSource.VLM,
        ),
        Clue(
            post_id=MOCK_POST_ID,
            image_index=0,
            type=ClueType.PHONE,
            value="03-0000-00xx",
            region=(400, 300, 560, 330),
            confidence=0.81,
            source=ClueSource.OCR,
        ),
        Clue(
            post_id=MOCK_POST_ID,
            image_index=0,
            type=ClueType.REFLECTION,
            value="瞳に建物が映り込んでいる",
            region=(610, 220, 640, 245),
            confidence=0.55,
            source=ClueSource.VLM,
        ),
        Clue(
            post_id=MOCK_POST_ID,
            image_index=None,
            type=ClueType.ROUTINE_TEXT,
            value="夜勤明け",
            region=None,
            confidence=0.9,
            source=ClueSource.TEXT,
        ),
    ]
)
