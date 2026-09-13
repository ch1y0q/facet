"""Tests for ``processing.scorer._sanitize_exif_numeric``.

Covers review finding 23: an unparseable numeric EXIF string (e.g. an
``iso`` field ExifTool reports as the literal ``"Auto"``) must be nulled
out rather than left in place as TEXT in an INTEGER/REAL-affinity column,
which raises ``ResponseValidationError`` on the gallery endpoints'
``response_model=``-typed numeric fields.
"""

from processing.scorer import _sanitize_exif_numeric


class TestSanitizeExifNumeric:
    def test_nulls_unparseable_string(self):
        exif_data = {'iso': 'Auto'}
        result = _sanitize_exif_numeric(exif_data)
        assert result['iso'] is None

    def test_nulls_non_finite_float(self):
        exif_data = {'f_stop': float('inf')}
        result = _sanitize_exif_numeric(exif_data)
        assert result['f_stop'] is None

    def test_nulls_nan(self):
        exif_data = {'focal_length': float('nan')}
        result = _sanitize_exif_numeric(exif_data)
        assert result['focal_length'] is None

    def test_numeric_string_iso_becomes_int(self):
        exif_data = {'iso': '400'}
        result = _sanitize_exif_numeric(exif_data)
        assert result['iso'] == 400
        assert isinstance(result['iso'], int)

    def test_fractional_iso_becomes_int(self):
        exif_data = {'iso': 63.4525478595867}
        result = _sanitize_exif_numeric(exif_data)
        assert result['iso'] == 63
        assert isinstance(result['iso'], int)

    def test_oversized_iso_is_nulled_not_rounded(self):
        """``round(1e20)`` is an int sqlite3 cannot bind, and this sanitiser
        feeds the batch INSERT -- so the bound is the same one the response
        model applies (``int_affinity.storable_int``) and the value is nulled.
        """
        result = _sanitize_exif_numeric({'iso': 1e20})
        assert result['iso'] is None

    def test_passes_through_valid_float(self):
        exif_data = {'f_stop': 2.8}
        result = _sanitize_exif_numeric(exif_data)
        assert result['f_stop'] == 2.8

    def test_leaves_none_untouched(self):
        exif_data = {'iso': None}
        result = _sanitize_exif_numeric(exif_data)
        assert result['iso'] is None

    def test_leaves_unrelated_keys_untouched(self):
        exif_data = {'camera_model': 'Canon EOS 600D'}
        result = _sanitize_exif_numeric(exif_data)
        assert result['camera_model'] == 'Canon EOS 600D'
