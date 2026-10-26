"""Check JPEG XL dimensions before the optional Pillow plugin eagerly decodes.

Only the codestream size header is read here, not image pixels or metadata.
SizeHeader is defined in libjxl's lib/jxl/headers.cc. Container boxes follow
ISO/IEC 18181-2; fragmented codestream prefixes are joined in index order.
"""

import os
import struct

from PIL import Image

_CONTAINER_SIGNATURE = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"
# Signature plus the largest possible size header (68 bits).
_PREFIX_BYTES = 11
_MAX_HEADER_BOXES = 4096
_RATIOS = ((1, 1), (12, 10), (4, 3), (3, 2), (16, 9), (5, 4), (2, 1))


def _codestream_prefix(stream):
    stream.seek(0, os.SEEK_END)
    end = stream.tell()
    stream.seek(0)
    signature = stream.read(12)
    if signature.startswith(b"\xff\x0a"):
        return signature[:_PREFIX_BYTES]
    if signature != _CONTAINER_SIGNATURE:
        raise ValueError("Invalid JPEG XL signature")
    prefix = bytearray()
    next_index = 0
    for _ in range(_MAX_HEADER_BOXES):
        start = stream.tell()
        header = stream.read(8)
        if len(header) != 8:
            break
        size, kind = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:
            extended = stream.read(8)
            if len(extended) != 8:
                raise ValueError("Truncated JPEG XL box header")
            size = struct.unpack(">Q", extended)[0]
            header_size = 16
        elif size == 0:
            size = end - start
        if size < header_size or start + size > end:
            raise ValueError("Invalid JPEG XL box size")
        payload_size = size - header_size
        if kind == b"jxlc":
            if prefix:
                raise ValueError("Mixed JPEG XL codestream boxes")
            return stream.read(min(_PREFIX_BYTES, payload_size))
        if kind == b"jxlp":
            if payload_size < 4:
                raise ValueError("Truncated JPEG XL fragment")
            index = struct.unpack(">I", stream.read(4))[0]
            if index & 0x7fffffff != next_index:
                raise ValueError("Out-of-order JPEG XL fragment")
            next_index += 1
            prefix.extend(stream.read(min(_PREFIX_BYTES - len(prefix), payload_size - 4)))
            if len(prefix) == _PREFIX_BYTES or index & 0x80000000:
                return bytes(prefix)
        stream.seek(start + size)
    raise ValueError("JPEG XL size header not found within 4096 boxes")


def jpegxl_dimensions(stream):
    """Read dimensions without decoding; restore the caller's stream position."""
    position = stream.tell()
    try:
        prefix = _codestream_prefix(stream)
    finally:
        stream.seek(position)
    if not prefix.startswith(b"\xff\x0a"):
        raise ValueError("Invalid JPEG XL codestream")
    data = int.from_bytes(prefix[2:], "little")
    available = (len(prefix) - 2) * 8
    offset = 0

    def bits(count):
        nonlocal offset
        if offset + count > available:
            raise ValueError("Truncated JPEG XL size header")
        value = (data >> offset) & ((1 << count) - 1)
        offset += count
        return value

    small = bits(1)

    def dimension():
        return (bits(5) + 1) * 8 if small else bits((9, 13, 18, 30)[bits(2)]) + 1

    height = dimension()
    ratio = bits(3)
    if ratio:
        numerator, denominator = _RATIOS[ratio - 1]
        width = height * numerator // denominator
    else:
        width = dimension()
    if not width or not height:
        raise ValueError("Empty JPEG XL image")
    return width, height


def register_bounded_jpegxl_opener():
    """Register only when installed; every Pillow consumer gets the same limit."""
    from pillow_jxl.JpegXLImagePlugin import JXLImageFile, _accept

    class BoundedJXLImageFile(JXLImageFile):
        def _open(self):
            width, height = jpegxl_dimensions(self.fp)
            if Image.MAX_IMAGE_PIXELS is not None and width * height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("JPEG XL image exceeds MAX_IMAGE_PIXELS limit")
            super()._open()
            # The plugin labels 16-bit grey+alpha bytes as 8-bit LA, and
            # exposes float greyscale without a display-range contract. Refuse
            # these rather than silently scoring/rendering corrupted pixels.
            if self.rawmode.startswith('F') or (
                self.rawmode == 'LA' and len(self._data) != self.width * self.height * 2
            ):
                raise ValueError("Unsupported JPEG XL floating-point or grayscale alpha bit depth")

    Image.register_open("JXL", BoundedJXLImageFile, _accept)
