"""MOCK_MODE で返す固定の手がかり。"""

from tkb_api.schemas import Clue, ClueSource, ClueType, DetectResponse

MOCK_RESPONSE = DetectResponse(
    clues=[
        Clue(
            type=ClueType.STATION_SIGN,
            value="新宿",
            region=(120, 80, 340, 150),
            confidence=0.92,
            source=ClueSource.VLM,
        ),
        Clue(
            type=ClueType.PHONE,
            value="03-0000-0000",
            region=(400, 300, 560, 330),
            confidence=0.81,
            source=ClueSource.OCR,
        ),
        Clue(
            type=ClueType.IRIS,
            value="瞳に建物が映り込んでいる",
            region=(610, 220, 640, 245),
            confidence=0.55,
            source=ClueSource.VLM,
        ),
    ]
)
