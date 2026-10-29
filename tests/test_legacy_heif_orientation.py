"""Controlled nontransposing HEIF decoder; real tone map, pixels and Pillow EXIF.

This models the older decoder contract without running an older pillow-heif
release. No pixels from the installed (possibly transposing) decoder enter the
native path: it receives an owned, unrotated uint16 sensor plane instead.
"""

from io import BytesIO
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageOps
import pytest

pillow_heif = pytest.importorskip('pillow_heif')

from config.scoring_config import merge_hdr_pq_tonemap_settings  # noqa: E402
from utils import image_loading  # noqa: E402


@pytest.fixture
def legacy_decoder(monkeypatch):
    def configure(orientation, marked):
        exif = Image.Exif()
        exif[274] = orientation
        exif[271] = 'Controlled camera'
        exif[272] = '00123'
        exif[306] = '2024:01:02 03:04:05'
        blob = exif.tobytes()
        assert blob.startswith(b'Exif\x00\x00')
        if not marked:
            blob = blob[6:]
        # Valid TIFF can contain padding beyond its referenced values. The
        # legacy branch must retain bytes, not merely reserialize equivalent tags.
        blob += b'\x00\x00legacy-padding\x00'
        levels = (np.arange(24, dtype=np.uint16).reshape(4, 6) * 30 + 20) << 6
        codes = np.repeat(levels[..., None], 3, axis=2)
        decoded = SimpleNamespace(
            mode='RGB;16', size=(6, 4), pixels=codes,
            __array_interface__=codes.__array_interface__,
            info={'bit_depth': 10, 'exif': blob},
        )
        state = SimpleNamespace(decoded=decoded, blob=blob, codes=codes,
                                native_calls=0, probe_calls=0, probe_sizes=[], headers=[])
        original_encoder = pillow_heif.from_pillow

        def encode_probe(image):
            state.probe_sizes.append(image.size)
            return original_encoder(image)

        def open_legacy(source, **kwargs):
            if isinstance(source, BytesIO):
                # The real capability probe encodes its real Pillow image.
                # A legacy decoder returns the stored plane dimensions unchanged.
                assert kwargs == {}
                assert source.tell() == 0 and source.getvalue()
                assert state.probe_sizes == [(6, 4)]
                state.probe_calls += 1
                return SimpleNamespace(size=state.probe_sizes[0])
            assert source == 'controlled-legacy.hif'
            assert kwargs == {'convert_hdr_to_8bit': False}
            state.native_calls += 1
            return decoded

        class HeaderPillow:
            """Metadata-only HEIF open modeled with a real, unrotated PIL image."""

            def open(self, source):
                assert source == 'controlled-legacy.hif'
                header = Image.fromarray((codes >> 8).astype(np.uint8))
                header.format = 'HEIF'
                header.info.update(exif=blob, nclx_profile={'transfer_characteristics': 16})
                state.headers.append(header)
                return header

            def __getattr__(self, name):
                return getattr(Image, name)

        settings = merge_hdr_pq_tonemap_settings({'enabled': True})
        monkeypatch.setattr(image_loading, '_heif_transposes', None)
        monkeypatch.setattr(image_loading, '_hdr_pq_tonemap_settings', settings)
        monkeypatch.setattr(image_loading, '_ensure_pil', lambda: (HeaderPillow(), ImageOps))
        monkeypatch.setattr(pillow_heif, 'from_pillow', encode_probe)
        monkeypatch.setattr(pillow_heif, 'open_heif', open_legacy)
        # Color correctness is covered by the real-file native-depth suites.
        # This spatial reference deliberately has no EXIF or orientation step.
        state.mapped = image_loading._tonemap_codes_to_srgb(
            codes, image_loading._pq_eotf_lut(10), 6, settings)
        state.original_codes = codes.copy()
        return state, settings

    return configure


@pytest.mark.parametrize('orientation', [6, 8, 3, 1])
@pytest.mark.parametrize('marked', [False, True], ids=['tiff-blob', 'exif-marker'])
def test_legacy_native_decode_preserves_verbatim_exif_and_sensor_layout(legacy_decoder, orientation, marked):
    state, settings = legacy_decoder(orientation, marked)
    native = image_loading._decode_pq_native('controlled-legacy.hif', settings)
    assert native is not None
    assert native.mode == 'RGB' and native.size == (6, 4)
    np.testing.assert_array_equal(np.asarray(native), state.mapped)
    assert native.info['exif'] == state.blob
    assert native.getexif()[274] == orientation
    assert native.getexif()[271] == 'Controlled camera'
    assert native.getexif()[272] == '00123'
    assert native.getexif()[306] == '2024:01:02 03:04:05'
    assert image_loading._heif_transposes is False
    assert image_loading._pillow_heif_transposes() is False
    assert state.probe_calls == 1 and state.probe_sizes == [(6, 4)]
    assert state.native_calls == 1 and state.headers == []
    np.testing.assert_array_equal(state.codes, state.original_codes)


@pytest.mark.parametrize('orientation,turns', [(6, -1), (8, 1), (3, 2), (1, 0)])
@pytest.mark.parametrize('marked', [False, True], ids=['tiff-blob', 'exif-marker'])
def test_public_loader_turns_legacy_pixels_once_and_preserves_other_metadata(
    legacy_decoder, orientation, turns, marked,
):
    state, _ = legacy_decoder(orientation, marked)
    upright = image_loading.open_nonraw_image('controlled-legacy.hif')
    expected = np.rot90(state.mapped, turns)
    assert upright.mode == 'RGB'
    assert upright.size == ((4, 6) if orientation in (6, 8) else (6, 4))
    np.testing.assert_array_equal(np.asarray(upright), expected)
    # Orientation 3 keeps the dimensions; asymmetric pixels distinguish its
    # half-turn from a no-op, and 6/8 distinguish clockwise from counterclockwise.
    if orientation in (3, 6, 8):
        assert not np.array_equal(expected, state.mapped)
    assert upright.getexif().get(274, 1) == 1
    assert upright.getexif()[271] == 'Controlled camera'
    assert upright.getexif()[272] == '00123'
    assert upright.getexif()[306] == '2024:01:02 03:04:05'
    np.testing.assert_array_equal(np.asarray(ImageOps.exif_transpose(upright)), expected)
    assert state.decoded.info['exif'] == state.blob
    np.testing.assert_array_equal(state.codes, state.original_codes)
    assert image_loading._heif_transposes is False
    assert state.native_calls == state.probe_calls == len(state.headers) == 1
