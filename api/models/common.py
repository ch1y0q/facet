"""Base classes shared by more than one module under ``api/models/``."""

from typing import Annotated, Optional

from pydantic import BaseModel, BeforeValidator

from int_affinity import storable_int


class PaginationEnvelope(BaseModel):
    """The ``{page, per_page, total, total_pages, has_more}`` shape shared by
    ``PhotosResponse``, ``AlbumPhotosResponse`` and ``SharedAlbumResponse``.

    Other paginated responses have already drifted from this exact shape --
    ``CapsulesResponse`` drops ``total_pages``, ``ScenesResponse`` drops
    ``has_more``, ``BurstGroupsResponse``/``CullingGroupsResponse`` use
    ``total_groups`` instead of ``total`` -- and must not be forced onto it.
    """

    page: int
    per_page: int
    total: int
    total_pages: int
    has_more: bool


def _coerce_int(value):
    """Turn what SQLite handed back for an INTEGER-affinity column into an int.

    Affinity is not a constraint: a column declared INTEGER still stores
    whatever storage class was written to it, so a REAL with a fractional
    part (``63.4525478595867``, an Immich-sourced EXIF exposure index --
    issue #142) or a TEXT value stays exactly that on read-back. A strict
    ``int`` field rejects it with ``int_from_float``/``int_parsing``, and
    because ``response_model`` validates the whole page at once, one such
    row turns into a 500 for every row on the page rather than one odd
    value in one tile.
    """
    if value is None or isinstance(value, (int, bool)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return storable_int(number)


CoercedInt = Annotated[Optional[int], BeforeValidator(_coerce_int)]
"""``Optional[int]`` that survives a REAL or TEXT storage class from SQLite.

Wraps ``Optional[int]`` rather than being wrapped in ``Optional`` on the
outside: inside a ``Union``, the validator has to live in the ``int`` arm, so
the ``None`` it returns for ``'Auto'``/``inf``/``nan``/bytes is accepted by
the ``None`` arm of the same union. Built the other way around -- an
``Optional`` wrapping a validated ``int`` -- that ``None`` return is checked
against the inner ``int`` arm alone and rejected as ``int_type``, which
turns a fractional-value 500 into a TEXT/NaN 500 instead of fixing it.
``storable_int`` reports a REAL beyond ``JS_SAFE_INT`` (``1e20`` -- the other
shape in which a REAL survives an INTEGER column) as unknown (``None``)
rather than as a wrong number, and the write path and the repair apply the
same bound, so none of the three can serve a value another one refused.
"""
