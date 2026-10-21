"""``api.model_cache.accelerator_lock``: one lock for every model the viewer
runs on MPS.

PyTorch's MPS backend is not thread-safe, and every model shares the one
device, so a search encoding while a saliency overlay renders aborts the
viewer inside Metal exactly as two searches do. CUDA and CPU stay unserialized.
"""

import io
import threading
import time
from unittest import mock

import numpy as np
from PIL import Image

from api.model_cache import _mps_lock, accelerator_lock, vlm_accelerator_lock


def test_mps_devices_share_one_lock():
    assert accelerator_lock("mps") is _mps_lock
    assert accelerator_lock("mps:0") is _mps_lock


def test_cuda_cpu_and_no_device_are_not_serialized():
    for device in ("cuda", "cuda:0", "cpu", None):
        assert accelerator_lock(device) is not _mps_lock


def test_a_remote_vlm_backend_takes_no_lock_even_on_a_mac():
    local = mock.Mock(backend=None, device="mps")
    remote = mock.Mock(backend=object(), device="mps")
    assert vlm_accelerator_lock(local) is _mps_lock
    assert vlm_accelerator_lock(remote) is not _mps_lock


def test_a_search_and_a_saliency_overlay_never_run_on_mps_at_once():
    from api.routers import saliency, search

    state = {"inside": 0, "peak": 0}
    guard = threading.Lock()

    def _occupy():
        with guard:
            state["inside"] += 1
            state["peak"] = max(state["peak"], state["inside"])
        time.sleep(0.02)
        with guard:
            state["inside"] -= 1

    class _Features:
        def cpu(self):
            return self

        def numpy(self):
            return np.ones((1, 4))

    def _fake_encode(*_a, **_k):
        _occupy()
        return _Features()

    class _FakeScorer:
        device = "mps"

        def get_saliency_soft(self, _pil):
            _occupy()
            return np.zeros((8, 8), dtype=np.float32)

    def _thumbnail(shade):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (shade, shade, shade)).save(buf, format="JPEG")
        return buf.getvalue()

    start = threading.Barrier(4)
    errors = []

    def _run(job):
        start.wait()
        try:
            job()
        except Exception as exc:  # surfaced below; a thread swallows it otherwise
            errors.append(exc)

    jobs = [
        lambda: search._encode_texts(["person"]),
        lambda: search._encode_texts(["beach"]),
        lambda: saliency._render_overlay(_thumbnail(10)),
        lambda: saliency._render_overlay(_thumbnail(200)),
    ]
    encoder = {"backend": "open_clip", "model": object(), "model_name": "ViT-L-14", "device": "mps"}
    saliency._render_overlay.cache_clear()
    try:
        with mock.patch.object(search, "_text_encoder", encoder), \
             mock.patch("models.tagger.encode_text_prompts", side_effect=_fake_encode), \
             mock.patch("api.model_cache.get_or_load_saliency_scorer", return_value=_FakeScorer()):
            threads = [threading.Thread(target=_run, args=(job,)) for job in jobs]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
    finally:
        saliency._render_overlay.cache_clear()

    assert errors == []
    assert state["peak"] == 1
