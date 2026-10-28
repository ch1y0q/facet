"""JPEG XL Pillow opener backed by the existing imagecodecs dependency.

Dimensions and bounded EXIF metadata are read without decoding image pixels.
SizeHeader is defined in libjxl's lib/jxl/headers.cc. Container boxes follow
ISO/IEC 18181-2; fragmented codestream prefixes are joined in index order.
"""

import os
import logging
from functools import lru_cache
from io import BytesIO
import struct

import numpy as np
from PIL import Image, ImageFile

logger = logging.getLogger(__name__)

_CONTAINER_SIGNATURE = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"
_MAX_HEADER_BOXES = 4096
_MAX_EXIF_BYTES = 16 * 1024 * 1024


def _container_boxes(stream, end):
    """Yield payload positions, skipping even large codestream/metadata boxes."""
    for _ in range(_MAX_HEADER_BOXES):
        start = stream.tell()
        if start == end:
            return
        header = stream.read(8)
        if len(header) != 8:
            raise ValueError("Truncated JPEG XL box header")
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
        yield kind, size - header_size
        stream.seek(start + size)
    if stream.tell() != end:
        raise ValueError("JPEG XL container exceeds 4096 boxes")


def _jpegxl_exif(stream):
    """Read standard Exif/brob-Exif with bounded encoded and decoded sizes."""
    position = stream.tell()
    try:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        stream.seek(0)
        if stream.read(12) != _CONTAINER_SIGNATURE:
            return None
        for kind, size in _container_boxes(stream, end):
            if kind == b"brob":
                if size < 4:
                    raise ValueError("Truncated JPEG XL compressed metadata")
                if stream.read(4) != b"Exif":
                    continue
                size -= 4
            elif kind != b"Exif":
                continue
            if size > _MAX_EXIF_BYTES:
                raise ValueError("JPEG XL EXIF exceeds metadata byte limit")
            payload = stream.read(size)
            if kind == b"brob":
                import imagecodecs
                try:
                    payload = bytes(imagecodecs.brotli_decode(payload, out=bytearray(_MAX_EXIF_BYTES)))
                except (ValueError, RuntimeError) as error:
                    raise ValueError("JPEG XL EXIF is invalid or exceeds metadata byte limit") from error
            # Some encoders write bare TIFF metadata. Recognise that
            # representation too; standards-compliant boxes use an offset.
            if payload[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
                return payload
            if len(payload) < 4:
                raise ValueError("Truncated JPEG XL EXIF offset")
            start = 4 + int.from_bytes(payload[:4], "big")
            if payload[start:start + 4] not in (b"II\x2a\x00", b"MM\x00\x2a"):
                raise ValueError("Invalid JPEG XL EXIF offset")
            return payload[start:]
        return None
    finally:
        stream.seek(position)


def _accept_jpegxl(prefix):
    return prefix.startswith(b"\xff\x0a") or prefix.startswith(_CONTAINER_SIGNATURE)


def _has_jpeg_reconstruction(stream):
    position = stream.tell()
    try:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        stream.seek(0)
        if stream.read(12) != _CONTAINER_SIGNATURE:
            return False
        return any(kind == b'jbrd' for kind, _ in _container_boxes(stream, end))
    except ValueError:
        return False
    finally:
        stream.seek(position)


def _read_exif_safely(stream, *, native: bool):
    try:
        raw = _jpegxl_exif(stream)
        if raw is None:
            return None
        parsed = Image.Exif()
        parsed.load(raw)
        # Validate the fields Pillow consumers actually inspect, before the
        # image is handed to exif_transpose or the scanner's metadata reader.
        dict(parsed)
        parsed.get_ifd(34665)
        parsed.get_ifd(34853)
        if native and 274 in parsed:
            parsed[274] = 1
        return parsed.tobytes()
    except MemoryError:
        raise
    except Exception as error:
        logger.debug("Ignoring unreadable JPEG XL EXIF: %s", error)
        return None


@lru_cache(maxsize=1)
def _decoder_returns_code_values():
    """Older imagecodecs scaled integer samples; newer releases retain depth."""
    import imagecodecs
    # Synthetic 1x1 white 10-bit RGB frame. Older encoders can silently write
    # 16 bits, so the probe must not depend on the installed encoder's behavior.
    encoded = bytes.fromhex('ff0a00101450b408080001002c004b188b15c259c11e80fe03')
    return imagecodecs.jpegxl_decode(encoded, index=0, numthreads=1).reshape(-1)[0] == 1023


def _pixel_image(pixels, bits_per_sample):
    """Build an 8-bit Pillow frame with bounded temporary scaling buffers."""
    if pixels.ndim not in (2, 3) or (pixels.ndim == 3 and pixels.shape[-1] not in (2, 3, 4)):
        raise ValueError("Unsupported JPEG XL channel layout")
    floating_point = pixels.dtype.kind == 'f'
    if floating_point:
        maximum = 1
    elif pixels.dtype.kind == 'u':
        maximum = np.iinfo(pixels.dtype).max
        if bits_per_sample not in (8, 16) and _decoder_returns_code_values():
            maximum = (1 << bits_per_sample) - 1
    else:
        raise ValueError("Unsupported JPEG XL sample type")
    if maximum != 255:
        output = np.empty(pixels.shape, dtype=np.uint8)
        channels = pixels.shape[-1] if pixels.ndim == 3 else 1
        rows = max(1, (4 * 1024 * 1024) // (pixels.shape[1] * channels * 4))
        for start in range(0, pixels.shape[0], rows):
            source = pixels[start:start + rows]
            # Lossy coding overshoots [0, 1] slightly even for SDR content, so
            # out-of-range floats clip below like every other sample type.
            if floating_point and not np.isfinite(source).all():
                raise ValueError("JPEG XL floating-point samples must be finite")
            band = np.multiply(source, 255.0 / maximum, dtype=np.float32)
            np.clip(band, 0, 255, out=band)
            band += 0.5
            output[start:start + rows] = band.astype(np.uint8)
        pixels = output
    return Image.fromarray(pixels)


class JpegXLImageFile(ImageFile.ImageFile):
    """Inspect headers lazily; decode only the first frame when pixels are used."""
    format = 'JXL'
    format_description = 'JPEG XL'

    def _open(self):
        from utils.jpegxl_header import jpegxl_basic_info
        self._basic_info = jpegxl_basic_info(self.fp)
        width, height = self._basic_info.width, self._basic_info.height
        if Image.MAX_IMAGE_PIXELS is not None and width * height > Image.MAX_IMAGE_PIXELS:
            raise ValueError("JPEG XL image exceeds MAX_IMAGE_PIXELS limit")
        self._reconstructed_jpeg = _has_jpeg_reconstruction(self.fp)
        self._size = ((height, width) if not self._reconstructed_jpeg and self._basic_info.orientation >= 5
                      else (width, height))
        self._mode = 'RGB'
        self.tile = []
        self._pixels_loaded = False
        self.n_frames = 1
        self.is_animated = False
        exif = _read_exif_safely(self.fp, native=not self._reconstructed_jpeg)
        if exif is not None:
            self.info['exif'] = exif

    def load(self):
        if not self._pixels_loaded:
            import imagecodecs
            self.fp.seek(0)
            encoded = self.fp.read()
            # The file/stream may have changed after lazy header inspection.
            # Validate the immutable bytes actually passed to the native codec.
            from utils.jpegxl_header import jpegxl_basic_info
            snapshot = BytesIO(encoded)
            current = jpegxl_basic_info(snapshot)
            if Image.MAX_IMAGE_PIXELS is not None and current.width * current.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("JPEG XL image exceeds MAX_IMAGE_PIXELS limit")
            if current != self._basic_info or _has_jpeg_reconstruction(snapshot) != self._reconstructed_jpeg:
                raise ValueError("JPEG XL headers changed before pixel decoding")
            exif = _read_exif_safely(snapshot, native=not self._reconstructed_jpeg)
            self.info.pop('exif', None)
            self._exif = None
            if exif is not None:
                self.info['exif'] = exif
            if self._reconstructed_jpeg:
                jpeg = imagecodecs.jpegxl_decode_jpeg(encoded, numthreads=1)
                with Image.open(BytesIO(jpeg)) as source:
                    plane = source.copy()
                    # Preserve JPEG ICC, but use the bounded/validated EXIF
                    # already read from the JXL container rather than bad TIFF.
                    self.info.update({k: v for k, v in source.info.items() if k != 'exif'})
            else:
                pixels = imagecodecs.jpegxl_decode(encoded, index=0, numthreads=1)
                plane = _pixel_image(pixels, self._basic_info.bits_per_sample)
            self._im = plane.im
            self._size = plane.size
            self._mode = plane.mode
            self._pixels_loaded = True
            if self._exclusive_fp:
                self.fp.close()
            self.fp = None
        return Image.Image.load(self)


def register_bounded_jpegxl_opener():
    """Enable standard/Docker installs when their core codec is available."""
    import imagecodecs
    if not imagecodecs.JPEGXL.available:
        return False
    Image.register_open('JXL', JpegXLImageFile, _accept_jpegxl)
    Image.register_extension('JXL', '.jxl')
    Image.register_mime('JXL', 'image/jxl')
    return True
