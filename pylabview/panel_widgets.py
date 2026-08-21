from __future__ import annotations

from typing import Any

from .integrations.vision_adapter import ImageFrame


def gauge_fraction(value: Any, minimum: Any, maximum: Any) -> float:
    low, high, number = float(minimum), float(maximum), float(value)
    if high <= low:
        raise ValueError("gauge maximum must exceed minimum")
    return max(0.0, min(1.0, (number - low) / (high - low)))


def table_rows(value: Any) -> list[list[Any]]:
    if not isinstance(value, list):
        return []
    return [list(row) for row in value if isinstance(row, (list, tuple))]


def next_dropdown_value(value: Any, options: Any) -> str:
    if not isinstance(options, list) or not options or any(not isinstance(option, str) for option in options):
        raise ValueError("dropdown options must be a non-empty string list")
    try:
        return options[(options.index(str(value)) + 1) % len(options)]
    except ValueError:
        return options[0]


def image_to_ppm(frame: ImageFrame, max_pixels: int = 1_000_000) -> bytes:
    if not isinstance(frame, ImageFrame):
        raise TypeError("thumbnail source must be an ImageFrame")
    dtype = getattr(frame.payload, "dtype", None)
    if str(getattr(dtype, "name", dtype)) != "uint8":
        raise ValueError("front-panel thumbnails require uint8 images")
    if frame.width * frame.height > max_pixels:
        raise ValueError("front-panel thumbnail source exceeds processing bound")
    rows = frame.payload.tolist()
    if frame.channels == 1:
        data = bytes(int(value) for row in rows for value in row)
        return f"P5\n{frame.width} {frame.height}\n255\n".encode("ascii") + data
    data = bytes(int(channel) for row in rows for pixel in row
                 for channel in (pixel[2], pixel[1], pixel[0]))
    return f"P6\n{frame.width} {frame.height}\n255\n".encode("ascii") + data
