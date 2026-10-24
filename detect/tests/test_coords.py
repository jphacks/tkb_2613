import pytest

from tkb_detect.coords import CoordinateSpace, to_original_region
from tkb_detect.image import Size

ORIGINAL = Size(3200, 1800)
SENT = Size(1280, 720)


def test_relative_1000_scales_to_original_pixels() -> None:
    region = to_original_region([100, 200, 500, 600], CoordinateSpace.RELATIVE_1000, SENT, ORIGINAL)

    assert region == (320, 360, 1600, 1080)


def test_sent_pixels_scale_up_to_original_pixels() -> None:
    region = to_original_region([128, 72, 640, 360], CoordinateSpace.SENT_PIXELS, SENT, ORIGINAL)

    assert region == (320, 180, 1600, 900)


def test_swapped_corners_are_put_in_order() -> None:
    region = to_original_region([500, 600, 100, 200], CoordinateSpace.RELATIVE_1000, SENT, ORIGINAL)

    assert region == (320, 360, 1600, 1080)


def test_clamps_to_the_image() -> None:
    region = to_original_region(
        [-10, -10, 1100, 1100], CoordinateSpace.RELATIVE_1000, SENT, ORIGINAL
    )

    assert region == (0, 0, 3200, 1800)


@pytest.mark.parametrize(
    "box",
    [
        [100, 100, 100, 200],  # 幅がない
        [1200, 1200, 1300, 1300],  # 画像の外
        [1, 2, 3],  # 要素数不足
    ],
)
def test_returns_none_without_area(box: list[float]) -> None:
    assert to_original_region(box, CoordinateSpace.RELATIVE_1000, SENT, ORIGINAL) is None
