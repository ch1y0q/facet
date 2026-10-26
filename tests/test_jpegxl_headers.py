"""JPEG XL preflight runs without the optional decoder or a pixel buffer."""
from io import BytesIO
import struct

import pytest

from utils.jpegxl import jpegxl_dimensions

_SIGNATURE = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"


def _box(kind, payload):
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def _size_header(width, height, selector):
    # Explicit-size encoding, no fixed aspect ratio. Selectors carry an unsigned
    # dimension minus one in 9/13/18/30 bits, respectively.
    bits = [(0, 1), (selector, 2), (height - 1, (9, 13, 18, 30)[selector]),
            (0, 3), (selector, 2), (width - 1, (9, 13, 18, 30)[selector])]
    value = 0
    count = 0
    for item, size in bits:
        value |= item << count
        count += size
    return b"\xff\x0a" + value.to_bytes((count + 7) // 8, "little")


@pytest.mark.parametrize("width,selector", [(511, 0), (8191, 1), (262143, 2), (1073741824, 3)])
def test_all_dimension_encodings_without_allocating_pixels(width, selector):
    assert jpegxl_dimensions(BytesIO(_size_header(width, 17, selector))) == (width, 17)


def test_large_metadata_is_skipped_without_reading_it():
    class BoundedReads(BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= 12
            return super().read(size)
    payload = _SIGNATURE + _box(b"xml ", b"x" * 1000000) + _box(b"jxlc", _size_header(511, 17, 0))
    stream = BoundedReads(payload)
    stream.seek(3)
    assert jpegxl_dimensions(stream) == (511, 17)
    assert stream.tell() == 3


@pytest.mark.parametrize("box", [
    struct.pack(">I4s", 1, b"jxlc"),  # missing extended size
    struct.pack(">I4sQ", 1, b"jxlc", 15),  # size shorter than header
    struct.pack(">I4s", 1000, b"jxlc"),  # extends beyond file
    _box(b"jxlp", struct.pack(">I", 1) + b"abcd"),  # first index must be zero
    _box(b"jxlp", b"abc"),  # truncated fragment index
])
def test_malformed_container_restores_stream_position(box):
    stream = BytesIO(_SIGNATURE + box)
    stream.seek(2)
    with pytest.raises(ValueError):
        jpegxl_dimensions(stream)
    assert stream.tell() == 2


def test_metadata_box_count_is_bounded():
    stream = BytesIO(_SIGNATURE + _box(b"free", b"") * 4097)
    with pytest.raises(ValueError, match="4096 boxes"):
        jpegxl_dimensions(stream)
