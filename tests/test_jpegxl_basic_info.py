"""JPEG XL integer depths and basic metadata without decoding pixels."""
from io import BytesIO
import struct

import numpy as np
import pytest

from utils.jpegxl_header import jpegxl_basic_info

imagecodecs = pytest.importorskip("imagecodecs")


@pytest.mark.parametrize("container", [False, True])
@pytest.mark.parametrize("dtype,depth,exponent", [
    (np.uint8, 8, 0), (np.uint16, 10, 0), (np.uint16, 12, 0),
    (np.uint16, 16, 0), (np.float16, 16, 5), (np.float32, 32, 8),
])
@pytest.mark.parametrize("shape", [(24, 40), (24, 40, 2), (24, 40, 4)])
def test_real_codestream_depths(tmp_path, dtype, depth, exponent, container, shape):
    data = imagecodecs.jpegxl_encode(
        np.zeros(shape, dtype=dtype), bitspersample=depth,
        lossless=True, usecontainer=container, numthreads=1,
    )
    stream = BytesIO(data)
    stream.seek(2)
    info = jpegxl_basic_info(stream)
    assert stream.tell() == 2
    assert (info.width, info.height) == (40, 24)
    assert (info.bits_per_sample, info.exponent_bits_per_sample) == (depth, exponent)
    assert info.orientation == 1
    assert not info.have_animation


def _encoded(fields):
    value = 0
    count = 0
    for item, width in fields:
        value |= item << count
        count += width
    return b"\xff\x0a" + value.to_bytes((count + 7) // 8, "little")


def _small_size(width=40, height=24):
    return [(1, 1), (height // 8 - 1, 5), (0, 3), (width // 8 - 1, 5)]


def test_default_basic_metadata():
    info = jpegxl_basic_info(BytesIO(_encoded(_small_size() + [(1, 1)])))
    assert info == (40, 24, 8, 0, 1, False)


def test_intrinsic_preview_and_animation_fields_are_skipped():
    fields = _small_size() + [
        (0, 1),  # non-default metadata
        (1, 1), (5, 3),  # extra fields, orientation6
        (1, 1),  # intrinsic dimensions follow
    ] + _small_size(80, 48) + [
        (1, 1),  # preview exists
        (1, 1), (0, 2), (1, 3),  # div8 preview: height16*8, square
        (1, 1),  # animation exists
        (2, 2), (99, 10),  # clock numerator100
        (2, 2), (6, 8),  # denominator7
        (1, 2), (2, 3), (1, 1),  # loop count2, timecodes enabled
        (0, 1), (1, 2),  # integer10bit samples
    ]
    info = jpegxl_basic_info(BytesIO(_encoded(fields)))
    assert info == (40, 24, 10, 0, 6, True)


def test_header_read_is_bounded_and_handles_fragments():
    data = imagecodecs.jpegxl_encode(np.zeros((24, 40, 3), np.uint16), bitspersample=12, lossless=True, numthreads=1)
    def box(kind, payload):
        return struct.pack(">I4s", len(payload) + 8, kind) + payload
    signature = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"
    payload = signature + box(b"xml ", b" " * 1000000)
    payload += box(b"jxlp", struct.pack(">I", 0) + data[:5])
    payload += box(b"jxlp", struct.pack(">I", 0x80000001) + data[5:])
    class BoundedReads(BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= 64
            return super().read(size)
    assert jpegxl_basic_info(BoundedReads(payload)).bits_per_sample == 12


@pytest.mark.parametrize("payload", [b"", b"\xff\x0a", _encoded(_small_size())])
def test_truncated_metadata_is_refused_and_position_restored(payload):
    stream = BytesIO(payload)
    stream.seek(min(1, len(payload)))
    position = stream.tell()
    with pytest.raises(ValueError):
        jpegxl_basic_info(stream)
    assert stream.tell() == position
