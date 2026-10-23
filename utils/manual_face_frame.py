"""Portable canonical-pixel identity, with bounded process-local decode reuse."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import os
import threading

import numpy as np

from utils.image_loading import (
    get_hdr_pq_tonemap_settings, get_raw_decode_settings, load_image_for_face_crop,
)

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
    """Local cache/race key only; filesystem identity is never persisted."""
    path = os.path.abspath(os.fspath(path))
    stat = os.stat(path)
    profile = json.dumps([get_raw_decode_settings(), get_hdr_pq_tonemap_settings()],
                         sort_keys=True, separators=(',', ':'))
    return (path, stat.st_dev, stat.st_ino, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns, profile)


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
    height, width = pixels.shape[:2]
    digest = hashlib.sha256(memoryview(pixels).cast('B')).hexdigest()
    identity = json.dumps(['upright-pixels-v1', width, height, digest],
                          separators=(',', ':'))
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
