import io

from PIL import Image, ImageDraw

from tkb_detect.near_duplicate import is_near_duplicate, perceptual_hash


def _picture(*, variant: int = 0, quality: int = 94) -> bytes:
    image = Image.new("RGB", (320, 240), "#dce5ed")
    draw = ImageDraw.Draw(image)
    draw.rectangle((18 + variant * 70, 20, 135 + variant * 55, 132), fill="#176b87")
    draw.ellipse((165, 35 + variant * 5, 255, 125 + variant * 5), fill="#db7a32")
    draw.line((15, 205, 302, 160 - variant * 15), fill="#202c39", width=9)
    draw.polygon([(40, 170), (86, 145 + variant * 12), (129, 185)], fill="#709c54")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality)
    return output.getvalue()


def test_detects_only_a_near_exact_reencoded_copy() -> None:
    original, copy = _picture(), _picture(quality=88)
    assert is_near_duplicate(original, original)
    assert perceptual_hash(original) is not None
    assert is_near_duplicate(original, copy)
    assert not is_near_duplicate(original, _picture(variant=1))


def test_rejects_blank_low_texture_and_color_changed_images() -> None:
    white = io.BytesIO()
    Image.new("RGB", (320, 240), "white").save(white, format="PNG")
    blue = io.BytesIO()
    Image.new("RGB", (320, 240), "blue").save(blue, format="PNG")
    assert perceptual_hash(white.getvalue()) is None
    assert not is_near_duplicate(white.getvalue(), white.getvalue())
    assert not is_near_duplicate(white.getvalue(), blue.getvalue())
