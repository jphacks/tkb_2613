"""Conservative in-process near-duplicate comparison for place reference images.

This deliberately recognizes only exact or extremely close image copies. It is not a
landmark recognizer and must not be used to infer a camera position.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PIXELS = 12_000_000
PHASH_DISTANCE_LIMIT = 2
SSIM_MIN = 0.985
ASPECT_RATIO_MAX_DELTA = 0.005
MIN_TEXTURE_STDDEV = 12.0


def perceptual_hash(data: bytes) -> int | None:
    """Return a 63-bit low-frequency hash, or None for malformed/oversized images."""
    image = _open_rgb(data)
    if image is None:
        return None
    pixels = np.asarray(
        image.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64
    )

    # A separable DCT-II on a fixed 32x32 raster. Keep the top-left 8x8
    # frequencies and compare each coefficient with the median (excluding DC).
    indexes = np.arange(32, dtype=np.float64)
    frequencies = indexes[:, None]
    basis = np.cos(np.pi * (2 * indexes[None, :] + 1) * frequencies / 64)
    basis[0] *= 1 / np.sqrt(2)
    basis *= np.sqrt(2 / 32)
    coefficients = (basis @ pixels @ basis.T)[:8, :8].reshape(-1)[1:]
    median = float(np.median(coefficients))
    value = 0
    for coefficient in coefficients:
        value = (value << 1) | int(coefficient > median)
    return value


def is_near_duplicate(left: bytes, right: bytes) -> bool:
    """Recognize near-identical copies, not different views of the same place."""
    image_pair = _image_pair(left, right)
    if image_pair is None:
        return False
    left_image, right_image = image_pair
    left_hash, right_hash = perceptual_hash(left), perceptual_hash(right)
    if left_hash is None or right_hash is None:
        return False
    if (left_hash ^ right_hash).bit_count() > PHASH_DISTANCE_LIMIT:
        return False
    return _global_ssim(left_image, right_image) >= SSIM_MIN


def _open_rgb(data: bytes) -> Image.Image | None:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                return None
            image = ImageOps.exif_transpose(opened).convert("RGB")
            gray = np.asarray(image.convert("L"), dtype=np.float64)
            if float(np.std(gray)) < MIN_TEXTURE_STDDEV:
                return None
            return image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None


def _image_pair(left: bytes, right: bytes) -> tuple[np.ndarray, np.ndarray] | None:
    left_image, right_image = _open_rgb(left), _open_rgb(right)
    if left_image is None or right_image is None:
        return None
    left_ratio = left_image.width / left_image.height
    right_ratio = right_image.width / right_image.height
    if abs(left_ratio - right_ratio) > ASPECT_RATIO_MAX_DELTA:
        return None
    size = (64, 64)
    left_pixels = np.asarray(left_image.resize(size, Image.Resampling.LANCZOS), dtype=np.float64)
    right_pixels = np.asarray(right_image.resize(size, Image.Resampling.LANCZOS), dtype=np.float64)
    return left_pixels, right_pixels


def _global_ssim(left: np.ndarray, right: np.ndarray) -> float:
    """Channel-averaged global SSIM; intentionally strict for the near-copy gate."""
    channels: list[float] = []
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    for index in range(3):
        x, y = left[:, :, index], right[:, :, index]
        mean_x, mean_y = float(np.mean(x)), float(np.mean(y))
        var_x, var_y = float(np.var(x)), float(np.var(y))
        covariance = float(np.mean((x - mean_x) * (y - mean_y)))
        numerator = (2 * mean_x * mean_y + c1) * (2 * covariance + c2)
        denominator = (mean_x**2 + mean_y**2 + c1) * (var_x + var_y + c2)
        channels.append(numerator / denominator if denominator else 0.0)
    return sum(channels) / len(channels)
