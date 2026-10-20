"""Image results for the agent: one thumbnail or a numbered contact sheet, bounded in pixels and bytes.

Both are fetched through the allow-listed ``thumbnail`` route, so visibility is the route's.
The returned JPEG never exceeds ``viewer.mcp.max_image_bytes``; the JSON envelope that
describes it is capped separately, because the base64 image is not counted against it.
"""

import asyncio
import math
from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw

from api.agent.internal_client import InternalClient, err, ok

THUMBNAIL_SIZES = (160, 256, 384, 512, 640)
MAX_THUMBNAIL_EDGE = 640
MAX_SHEET_EDGE = 1024
MAX_SHEET_PATHS = 16
TILE_STEPS = (256, 192, 128)
SHEET_QUALITY = 72
THUMBNAIL_QUALITY = 80
JPEG_MIME = "image/jpeg"
BLANK_TILE = (58, 58, 62)
CHIP_FILL = (0, 0, 0)
CHIP_TEXT = (255, 255, 255)


def _clamp_edge(data: bytes, limit: int) -> tuple[bytes, int, int]:
    """The JPEG with its longest edge at most ``limit`` (re-encoded only when it was larger)."""
    image = Image.open(BytesIO(data))
    width, height = image.size
    if max(width, height) <= limit:
        return data, width, height
    image = image.convert("RGB")
    image.thumbnail((limit, limit), Image.LANCZOS)
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=THUMBNAIL_QUALITY)
    return buf.getvalue(), image.size[0], image.size[1]


def _too_large(max_bytes: int) -> dict:
    return err("too_large", f"Even the smallest image is over viewer.mcp.max_image_bytes ({max_bytes} bytes)")


async def thumbnail_result(client: InternalClient, grant, path: str, size: int, settings: dict) -> dict:
    """One thumbnail, stepping down a size until the JPEG fits ``max_image_bytes``."""
    cap = settings["max_image_bytes"]
    for step in [s for s in THUMBNAIL_SIZES if s <= size][::-1]:
        fetched = await client.call_bytes(grant, "thumbnail", query={"path": path, "size": step},
                                          timeout=settings["call_timeout_s"])
        if not fetched["ok"]:
            return fetched
        try:
            data, width, height = await asyncio.to_thread(
                _clamp_edge, fetched["data"]["bytes"], MAX_THUMBNAIL_EDGE)
        except (OSError, ValueError):
            return err("upstream_error", "The thumbnail could not be decoded")
        if len(data) <= cap:
            return ok({"path": path, "size": step, "width": width, "height": height, "bytes": len(data)},
                      _images=[(data, JPEG_MIME)])
    return _too_large(cap)


def _tile(data: bytes, tile: int, index: int) -> Image.Image:
    canvas = Image.new("RGB", (tile, tile), BLANK_TILE)
    draw = ImageDraw.Draw(canvas)
    if data:
        photo = Image.open(BytesIO(data)).convert("RGB")
        photo.thumbnail((tile, tile), Image.LANCZOS)
        canvas.paste(photo, ((tile - photo.size[0]) // 2, (tile - photo.size[1]) // 2))
    else:
        draw.text((6, tile // 2 - 5), "unavailable", fill=CHIP_TEXT)
    label = str(index)
    draw.rectangle((0, 0, 8 + 6 * len(label), 14), fill=CHIP_FILL)
    draw.text((4, 2), label, fill=CHIP_TEXT)
    return canvas


def _compose(blobs: list[bytes], columns: int, tile: int) -> tuple[bytes, int, int]:
    rows = math.ceil(len(blobs) / columns)
    sheet = Image.new("RGB", (columns * tile, rows * tile), BLANK_TILE)
    for position, data in enumerate(blobs):
        sheet.paste(_tile(data, tile, position + 1), ((position % columns) * tile, (position // columns) * tile))
    buf = BytesIO()
    sheet.save(buf, format="JPEG", quality=SHEET_QUALITY)
    return buf.getvalue(), sheet.size[0], sheet.size[1]


def _shrink_tiles(blobs: list[bytes], columns: int, cap: int, rows: int) -> Optional[tuple[bytes, int, int, int]]:
    """The first tile size (largest first) whose sheet fits ``cap`` and the pixel bound, else None."""
    limit = min(MAX_SHEET_EDGE // columns, MAX_SHEET_EDGE // rows)
    for step in dict.fromkeys(min(s, limit) for s in TILE_STEPS):
        data, width, height = _compose(blobs, columns, step)
        if len(data) <= cap:
            return data, width, height, step
    return None


async def contact_sheet_result(client: InternalClient, grant, paths: list[str], columns: int,
                               settings: dict) -> dict:
    """A numbered grid of the photos; ``legend`` and ``unavailable`` name them by index."""
    cap = settings["max_image_bytes"]
    rows = math.ceil(len(paths) / columns)
    fetch_size = min(TILE_STEPS[0], MAX_SHEET_EDGE // columns, MAX_SHEET_EDGE // rows)
    fetched = await asyncio.gather(*(
        client.call_bytes(grant, "thumbnail", query={"path": path, "size": fetch_size},
                          timeout=settings["call_timeout_s"]) for path in paths))
    blobs: list[bytes] = []
    unavailable: list[dict] = []
    for index, (path, reply) in enumerate(zip(paths, fetched), start=1):
        if reply["ok"]:
            blobs.append(reply["data"]["bytes"])
        else:
            blobs.append(b"")
            unavailable.append({"index": index, "path": path, "reason": reply.get("error", "unavailable")})
    try:
        fitted = await asyncio.to_thread(_shrink_tiles, blobs, columns, cap, rows)
    except (OSError, ValueError):
        return err("upstream_error", "A thumbnail could not be decoded")
    if fitted is None:
        return _too_large(cap)
    data, width, height, tile = fitted
    return ok({"columns": columns, "tile": tile, "width": width, "height": height, "bytes": len(data),
               "legend": [{"index": i, "path": p} for i, p in enumerate(paths, start=1)],
               "unavailable": unavailable}, _images=[(data, JPEG_MIME)])
