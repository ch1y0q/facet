"""Bounded JPEG XL basic information, without decoding image pixels.

Field order follows libjxl's lib/jxl/headers.cc and image_metadata.cc.
Only the size and basic metadata preceding channel/color information are read.
"""

import os
from typing import NamedTuple

_HEADER_BYTES = 64
_RATIOS = ((1, 1), (12, 10), (4, 3), (3, 2), (16, 9), (5, 4), (2, 1))


class JpegXLBasicInfo(NamedTuple):
    width: int
    height: int
    bits_per_sample: int
    exponent_bits_per_sample: int
    orientation: int
    have_animation: bool


class _Bits:
    def __init__(self, data: bytes):
        self.value = int.from_bytes(data, "little")
        self.available = len(data) * 8
        self.offset = 0

    def read(self, count: int) -> int:
        if count < 0 or self.offset + count > self.available:
            raise ValueError("Truncated JPEG XL basic information")
        value = (self.value >> self.offset) & ((1 << count) - 1)
        self.offset += count
        return value

    def u32(self, options) -> int:
        width, offset = options[self.read(2)]
        return self.read(width) + offset


def _prefix(stream) -> bytes:
    # Imported at call time so the registered opener can itself import this
    # basic-info reader without a module initialization cycle.
    from utils.jpegxl import _CONTAINER_SIGNATURE, _container_boxes

    position = stream.tell()
    try:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        stream.seek(0)
        signature = stream.read(12)
        if signature.startswith(b"\xff\x0a"):
            stream.seek(0)
            return stream.read(_HEADER_BYTES)
        if signature != _CONTAINER_SIGNATURE:
            raise ValueError("Invalid JPEG XL signature")
        prefix = bytearray()
        next_index = 0
        for kind, size in _container_boxes(stream, end):
            if kind == b"jxlc":
                if prefix:
                    raise ValueError("Mixed JPEG XL codestream boxes")
                return stream.read(min(size, _HEADER_BYTES))
            if kind != b"jxlp":
                continue
            if size < 4:
                raise ValueError("Truncated JPEG XL fragment")
            index = int.from_bytes(stream.read(4), "big")
            if index & 0x7fffffff != next_index:
                raise ValueError("Out-of-order JPEG XL fragment")
            next_index += 1
            prefix.extend(stream.read(min(size - 4, _HEADER_BYTES - len(prefix))))
            if len(prefix) == _HEADER_BYTES or index & 0x80000000:
                return bytes(prefix)
        raise ValueError("JPEG XL codestream not found")
    finally:
        stream.seek(position)


def _size(bits: _Bits) -> tuple[int, int]:
    small = bits.read(1)

    def dimension():
        if small:
            return (bits.read(5) + 1) * 8
        return bits.u32(((9, 1), (13, 1), (18, 1), (30, 1)))

    height = dimension()
    ratio = bits.read(3)
    if ratio:
        numerator, denominator = _RATIOS[ratio - 1]
        width = height * numerator // denominator
    else:
        width = dimension()
    if width == 0:
        raise ValueError("Empty JPEG XL image")
    return width, height


def _skip_preview(bits: _Bits) -> None:
    div8 = bits.read(1)
    options = (((0, 16), (0, 32), (5, 1), (9, 33)) if div8
               else ((6, 1), (8, 65), (10, 321), (12, 1345)))
    bits.u32(options)
    if bits.read(3) == 0:
        bits.u32(options)


def _skip_animation(bits: _Bits) -> None:
    numerator = bits.u32(((0, 100), (0, 1000), (10, 1), (30, 1)))
    denominator = bits.u32(((0, 1), (0, 1001), (8, 1), (10, 1)))
    if not numerator or not denominator:
        raise ValueError("Invalid JPEG XL animation clock")
    bits.u32(((0, 0), (3, 0), (16, 0), (32, 0)))
    bits.read(1)  # per-frame timecodes


def jpegxl_basic_info(stream) -> JpegXLBasicInfo:
    """Read at most 64 codestream bytes and restore the stream position.

    Width and height describe the stored pixel plane. A decoder applying
    orientations 5-8 swaps those dimensions; the pixel count is unchanged.
    """
    prefix = _prefix(stream)
    if not prefix.startswith(b"\xff\x0a"):
        raise ValueError("Invalid JPEG XL codestream")
    bits = _Bits(prefix[2:])
    width, height = _size(bits)
    if bits.read(1):  # all ImageMetadata fields are default
        return JpegXLBasicInfo(width, height, 8, 0, 1, False)
    orientation = 1
    animation = False
    if bits.read(1):  # non-default extra fields
        orientation = bits.read(3) + 1
        if bits.read(1):
            _size(bits)  # intrinsic dimensions
        if bits.read(1):
            _skip_preview(bits)
        animation = bool(bits.read(1))
        if animation:
            _skip_animation(bits)
    floating_point = bits.read(1)
    if floating_point:
        depth = bits.u32(((0, 32), (0, 16), (0, 24), (6, 1)))
        exponent = bits.read(4) + 1
        if not 2 <= exponent <= 8 or not 2 <= depth - exponent - 1 <= 23:
            raise ValueError("Invalid JPEG XL floating-point depth")
    else:
        depth = bits.u32(((0, 8), (0, 10), (0, 12), (6, 1)))
        exponent = 0
        if depth > 31:
            raise ValueError("Invalid JPEG XL integer depth")
    return JpegXLBasicInfo(width, height, depth, exponent, orientation, animation)
