"""Portable canonical-pixel identity, with bounded process-local decode reuse."""
from collections import OrderedDict
from dataclasses import dataclass
import json
import logging
import os
import threading

import cv2
import numpy as np

from utils.image_loading import (
    get_hdr_pq_tonemap_settings, get_raw_decode_settings, load_image_for_face_crop,
)

logger = logging.getLogger(__name__)
IDENTITY_VERSION = 2
IDENTITY_GRID = 8
# Mean absolute difference of the 8x8 grayscale signatures (0-255 scale) up to
# which two decodes count as the same picture: absorbs decoder-build noise
# (libjpeg IDCT, LibRaw demosaic, libheif tone-map) without absorbing a
# different image.
SIGNATURE_TOLERANCE = 3
_MAX_IDENTITIES = 128
_MAX_FRAME_BYTES = 128 * 1024 * 1024
_lock = threading.Lock()
_condition = threading.Condition(_lock)
_pending: set[tuple] = set()
_identities: OrderedDict[tuple, str] = OrderedDict()


@dataclass(frozen=True)
class FaceFrame:
    stamp: tuple
    identity: str
    pixels: np.ndarray


_last_frame: FaceFrame | None = None


def file_stamp(path):
    """Local cache/race key; its dev/ino/size/mtime are persisted only as a fast path, never as the proof."""
    path = os.path.abspath(os.fspath(path))
    stat = os.stat(path)
    profile = json.dumps([get_raw_decode_settings(), get_hdr_pq_tonemap_settings()],
                         sort_keys=True, separators=(',', ':'))
    return (path, stat.st_dev, stat.st_ino, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns, profile)


def pixel_identity(pixels, stat):
    """Portable identity: frame size and an 8x8 grayscale signature of the
    decoded frame, plus the file's stat (a fast path, never the proof)."""
    height, width = pixels.shape[:2]
    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    sig = cv2.resize(gray, (IDENTITY_GRID, IDENTITY_GRID), interpolation=cv2.INTER_AREA)
    return json.dumps({'v': IDENTITY_VERSION, 'w': width, 'h': height,
                       'sig': [int(x) for x in sig.flatten()], 'stat': stat},
                      separators=(',', ':'))


def _parse(identity):
    """Current-format identity as a dict; any other stored form is None.

    The earlier list forms (stat-only, SHA-256 of the pixels) are deliberately
    not understood: such a mark reads as needing review.
    """
    try:
        data = json.loads(identity) if identity else None
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get('v') == IDENTITY_VERSION else None


def same_image(first, second):
    """Same frame size and signatures within SIGNATURE_TOLERANCE."""
    a, b = _parse(first), _parse(second)
    if a is None or b is None:
        return False
    if (a['w'], a['h']) != (b['w'], b['h']) or len(a['sig']) != len(b['sig']):
        return False
    return sum(abs(x - y) for x, y in zip(a['sig'], b['sig'])) / len(a['sig']) <= SIGNATURE_TOLERANCE


def is_current(path, stored, conn=None, face_id=None, *, verify_pixels=False):
    """Is ``stored`` still the picture at ``path``? Never raises.

    An unchanged stat is current without decoding. Otherwise the file is
    decoded and compared by size and signature, so a metadata-only rewrite, a
    remount or another host's decoder does not stale the mark; where ``conn``
    is given the stored stat is then refreshed, best effort.
    """
    try:
        data = _parse(stored)
        if data is None:
            return False
        # An offline relink cannot prove the missing original's pixels from a
        # coarse signature. Preserve the annotation, but require an explicit
        # editor save on the new path before it can export or hide detections.
        if data.get('relink_unverified'):
            return False
        stat = os.stat(path)
        if not verify_pixels and data['stat'] == [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]:
            return True
        fresh = source_identity(path)
        if not same_image(stored, fresh):
            return False
        if conn is not None and face_id is not None:
            try:
                # Keep the original signature: refreshing it too would let
                # successive small drifts walk away from the drawn picture.
                conn.execute('UPDATE faces SET manual_source=? WHERE id=?',
                             (json.dumps({**data, 'stat': json.loads(fresh)['stat']},
                                         separators=(',', ':')), face_id))
            except Exception:
                logger.debug('could not refresh the stored identity of face %s', face_id, exc_info=True)
        return True
    except Exception:
        return False


def _load(stamp):
    global _last_frame
    try:
        pixels = load_image_for_face_crop(stamp[0])
    except (OSError, ValueError, RuntimeError) as exc:
        raise OSError('Original image could not be decoded') from exc
    if (not isinstance(pixels, np.ndarray) or pixels.ndim != 3 or pixels.shape[2] != 3 or
            pixels.dtype != np.uint8 or not pixels.shape[0] or not pixels.shape[1]):
        raise OSError('Original image could not be decoded')
    pixels = np.ascontiguousarray(pixels)
    identity = pixel_identity(pixels, list(stamp[1:5]))
    pixels.setflags(write=False)
    frame = FaceFrame(stamp, identity, pixels)
    # Decode/hash without the lock. A late decode cannot publish an old file
    # over a newer snapshot, and only one bounded array remains retained.
    with _lock:
        if file_stamp(stamp[0]) != stamp:
            raise OSError('Image changed while decoding')
        _identities[stamp] = identity
        _identities.move_to_end(stamp)
        while len(_identities) > _MAX_IDENTITIES:
            _identities.popitem(last=False)
        if pixels.nbytes <= _MAX_FRAME_BYTES:
            _last_frame = frame
    return frame


def read_frame(path):
    stamp = file_stamp(path)
    with _condition:
        while True:
            if _last_frame is not None and _last_frame.stamp == stamp:
                return _last_frame
            if stamp not in _pending:
                _pending.add(stamp)
                break
            _condition.wait()
    return _complete_load(stamp)


def source_identity(path):
    stamp = file_stamp(path)
    with _condition:
        while True:
            if _last_frame is not None and _last_frame.stamp == stamp:
                return _last_frame.identity
            identity = _identities.get(stamp)
            if identity is not None:
                _identities.move_to_end(stamp)
                return identity
            if stamp not in _pending:
                _pending.add(stamp)
                break
            _condition.wait()
    return _complete_load(stamp).identity


def _complete_load(stamp):
    try:
        return _load(stamp)
    finally:
        with _condition:
            _pending.discard(stamp)
            _condition.notify_all()


def clear_cache():
    global _last_frame
    with _lock:
        _identities.clear()
        _last_frame = None


def invalidate_path(path):
    """An explicit refresh discards only this original's cached frame/signature."""
    global _last_frame
    absolute = os.path.abspath(os.fspath(path))
    with _lock:
        for stamp in list(_identities):
            if stamp[0] == absolute:
                del _identities[stamp]
        if _last_frame is not None and _last_frame.stamp[0] == absolute:
            _last_frame = None
