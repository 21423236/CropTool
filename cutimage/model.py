from __future__ import annotations

import math
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int
    name: str
    uid: str = ""

    def __post_init__(self):
        if not self.uid:
            self.uid = uuid.uuid4().hex

    def snapshot(self):
        return asdict(self)


def new_bounds(x1, y1, x2, y2, image_width, image_height):
    """Enclose dragged pixels; right/bottom coordinates are exclusive."""
    left = max(0, min(image_width - 1, math.floor(min(x1, x2))))
    top = max(0, min(image_height - 1, math.floor(min(y1, y2))))
    right = max(left + 1, min(image_width, math.ceil(max(x1, x2))))
    bottom = max(top + 1, min(image_height, math.ceil(max(y1, y2))))
    return left, top, right - left, bottom - top


def moved_bounds(region, dx, dy, image_width, image_height):
    return (
        max(0, min(image_width - region.width, round(region.x + dx))),
        max(0, min(image_height - region.height, round(region.y + dy))),
        region.width,
        region.height,
    )


def resized_bounds(region, handle, dx, dy, image_width, image_height):
    left, top = region.x, region.y
    right, bottom = left + region.width, top + region.height
    if "w" in handle:
        left = max(0, min(right - 1, round(left + dx)))
    if "e" in handle:
        right = max(left + 1, min(image_width, round(right + dx)))
    if "n" in handle:
        top = max(0, min(bottom - 1, round(top + dy)))
    if "s" in handle:
        bottom = max(top + 1, min(image_height, round(bottom + dy)))
    return left, top, right - left, bottom - top


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(". ")
    if not name:
        name = "选区"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        name = "_" + name
    return name[:100]


def export_regions(image, regions, directory):
    """Export original-resolution pixels, creating files exclusively."""
    from PySide6.QtCore import QBuffer, QIODevice

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for region in regions:
            if not (0 <= region.x < image.width() and 0 <= region.y < image.height()
                    and 1 <= region.width <= image.width() - region.x
                    and 1 <= region.height <= image.height() - region.y):
                raise ValueError(f"选区超出图片边界：{region.name}")
            cropped = image.copy(region.x, region.y, region.width, region.height)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if not cropped.save(buffer, "PNG"):
                raise OSError(f"无法编码图片：{region.name}")
            data = bytes(buffer.data())
            buffer.close()
            stem = safe_filename(region.name)
            number = 1
            while True:
                suffix = "" if number == 1 else f"_{number}"
                destination = directory / f"{stem}{suffix}.png"
                try:
                    stream = destination.open("xb")
                    break
                except FileExistsError:
                    number += 1
            try:
                with stream:
                    stream.write(data)
            except Exception:
                destination.unlink(missing_ok=True)
                raise
            written.append(destination)
    except Exception as exc:
        raise OSError(f"已导出 {len(written)} 张；导出中断：{exc}") from exc
    return written
