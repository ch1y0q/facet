"""One rule for making a number fit an INTEGER-affinity SQLite column.

SQLite affinity is advisory: a column declared INTEGER stores whatever storage
class was written to it and narrows a REAL only when the conversion is
lossless AND the result fits int64. So a REAL survives in such a column in
exactly two shapes -- one with a fractional part (``63.4525478595867``, the
Immich-sourced EXIF exposure index of issue #142) and one too large for int64
(``1e20``) -- and any code rounding the first has to answer for the second:
``round(1e20)`` is a Python int SQLite cannot bind, so it raises
``OverflowError`` rather than storing anything.

Four call sites need this and must not disagree, which is why the rule lives
here and not in any one of them: the two EXIF parsers that write the column
(``exiftool.exiftool_batch.parse_exif_data``,
``processing.scorer._sanitize_exif_numeric``), the repair that rewrites values
a library already holds (``db.maintenance.repair_integer_columns``) and the
response model that serves them (``api.models.common.CoercedInt``). A top-level
stdlib-only module is the only place all four can import from without
inverting the layering -- ``exiftool/`` and ``processing/`` are below ``db/``,
which is below ``api/`` -- the same reason ``config_resolve`` sits here.

``JS_SAFE_INT`` rather than int64 is the bound because the value ends up in a
JSON document a browser parses: an int above 2**53 arrives in the client with
lost precision, so reporting it as unknown is honest where reporting a
near-miss integer is not.
"""

import math

JS_SAFE_INT = 2 ** 53 - 1


def storable_int(number):
    """Round ``number`` to an int an INTEGER column can hold, or ``None``.

    ``None`` covers both values SQLite cannot store faithfully -- non-finite
    (``nan``/``inf``) and beyond ``JS_SAFE_INT`` -- because NULL is the
    column's own word for "unknown". The alternative, leaving the REAL in
    place, is what issue #142 was.
    """
    if not math.isfinite(number) or abs(number) > JS_SAFE_INT:
        return None
    return round(number)
