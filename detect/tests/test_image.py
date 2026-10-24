import io

import pytest
from PIL import Image

from tkb_detect.errors import DetectError
from tkb_detect.image import MAX_LONG_SIDE, Size, prepare_image


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "PNG")
    return buf.getvalue()


def _jpeg_with_exif(width: int, height: int, orientation: int) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    exif = Image.Exif()
    exif[0x0112] = orientation  # Orientation
    exif[0x010F] = "SecretCamera"  # Make
    buf = io.BytesIO()
    image.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_shrinks_long_side_to_limit_and_keeps_original_size() -> None:
    prepared = prepare_image(_png(3200, 1800))

    assert prepared.original == Size(3200, 1800)
    assert prepared.sent == Size(MAX_LONG_SIDE, 720)
    with Image.open(io.BytesIO(prepared.jpeg)) as sent:
        assert sent.format == "JPEG"
        assert sent.size == (MAX_LONG_SIDE, 720)


def test_does_not_enlarge_small_images() -> None:
    prepared = prepare_image(_png(640, 480))

    assert prepared.sent == prepared.original == Size(640, 480)


def test_applies_exif_orientation_and_drops_metadata() -> None:
    # 6 は「90度回して表示する」。縦長として扱う
    prepared = prepare_image(_jpeg_with_exif(400, 300, orientation=6))

    assert prepared.original == Size(300, 400)
    with Image.open(io.BytesIO(prepared.jpeg)) as sent:
        assert len(sent.getexif()) == 0


def test_rejects_data_that_is_not_an_image() -> None:
    with pytest.raises(DetectError):
        prepare_image(b"not an image")
