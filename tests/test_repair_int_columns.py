"""Repair of INTEGER-affinity `photos` columns an external writer stored as REAL.

The invariant this defends (GitHub #142): SQLite affinity is advisory, so a
column declared INTEGER (e.g. `iso`) can still hold a fractional REAL written
by an external tool (an Immich-sourced EXIF exposure index). The repair must
find every such column by SQLite's own affinity rule, fix each offending row
in isolation so one row's unrelated CHECK violation cannot abort the rest, and
be idempotent -- a second run over an already-clean library reports zero.

Mirrors tests/test_channel_clipping.py's harness for a `db/maintenance.py` job
paired with a `LIBRARY_JOB_ARGS` membership assertion.
"""

import sqlite3

import pytest

from db.maintenance import repair_integer_columns
from db.schema import init_database, PHOTOS_COLUMNS


@pytest.fixture()
def repair_db(tmp_path):
    db_path = str(tmp_path / "repair.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO photos (path, filename, iso) VALUES (?, ?, ?)",
        ("/r/fractional.jpg", "fractional.jpg", 63.4525478595867))
    conn.execute(
        "INSERT INTO photos (path, filename, iso) VALUES (?, ?, ?)",
        ("/r/clean.jpg", "clean.jpg", 400))
    conn.execute(
        "INSERT INTO photos (path, filename, iso) VALUES (?, ?, ?)",
        ("/r/unset.jpg", "unset.jpg", None))
    conn.commit()
    conn.close()
    return db_path


def _row(db_path, path, col):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        f"SELECT typeof({col}), {col} FROM photos WHERE path = ?", (path,)).fetchone()
    conn.close()
    return row


class TestRepair:
    def test_a_fractional_value_is_rounded_and_stored_as_integer(self, repair_db):
        assert repair_integer_columns(repair_db, verbose=False) == 1
        storage_class, value = _row(repair_db, "/r/fractional.jpg", "iso")
        assert storage_class == "integer"
        assert value == 63

    def test_a_non_finite_value_is_repaired_to_null_rather_than_raising(self, repair_db):
        """``round(float('inf'))`` raises, and this job exists for bad data.

        NULL is the column's own word for unknown, and it is already what the
        response model serves for such a value -- so the repair agrees with it
        instead of crashing on the row it was run to fix. A NaN never reaches
        the repair at all: SQLite has no NaN and stores one as NULL, which is
        asserted here so the day that changes is not a crash.
        """
        conn = sqlite3.connect(repair_db)
        conn.execute(
            "INSERT INTO photos (path, filename, iso) VALUES (?, ?, ?)",
            ("/r/nan.jpg", "nan.jpg", float('nan')))
        conn.execute(
            "INSERT INTO photos (path, filename, iso) VALUES (?, ?, ?)",
            ("/r/inf.jpg", "inf.jpg", float('inf')))
        conn.commit()
        conn.close()
        assert _row(repair_db, "/r/nan.jpg", "iso") == ("null", None)

        assert repair_integer_columns(repair_db, verbose=False) == 2
        assert _row(repair_db, "/r/inf.jpg", "iso") == ("null", None)
        assert _row(repair_db, "/r/nan.jpg", "iso") == ("null", None)

    def test_an_oversized_value_does_not_abort_the_job_for_every_later_row(self, repair_db):
        """The other way a REAL survives an INTEGER column is by not fitting
        int64 -- ``iso = 1e20``. ``round`` turns that into a Python int
        sqlite3 cannot bind, and the resulting ``OverflowError`` is not an
        ``IntegrityError``, so it would escape the per-row guard, abort the
        run, and leave every row ordered after it unrepaired on this and on
        every later run. NULL instead, which is what the response model
        already serves for such a value.

        The later row is named so it sorts after the offending one, since the
        scan returns rows in rowid order and insertion order fixes that here.
        """
        conn = sqlite3.connect(repair_db)
        conn.execute(
            "INSERT INTO photos (path, filename, iso) VALUES (?, ?, ?)",
            ("/r/huge.jpg", "huge.jpg", 1e20))
        conn.execute(
            "INSERT INTO photos (path, filename, iso) VALUES (?, ?, ?)",
            ("/r/zz-after-huge.jpg", "zz-after-huge.jpg", 99.6))
        conn.commit()
        conn.close()

        assert repair_integer_columns(repair_db, verbose=False) == 3
        assert _row(repair_db, "/r/huge.jpg", "iso") == ("null", None)
        assert _row(repair_db, "/r/zz-after-huge.jpg", "iso") == ("integer", 100)
        assert _row(repair_db, "/r/fractional.jpg", "iso") == ("integer", 63)
        assert repair_integer_columns(repair_db, verbose=False) == 0

    def test_an_already_integer_row_is_untouched(self, repair_db):
        repair_integer_columns(repair_db, verbose=False)
        storage_class, value = _row(repair_db, "/r/clean.jpg", "iso")
        assert storage_class == "integer"
        assert value == 400

    def test_a_null_row_is_untouched(self, repair_db):
        repair_integer_columns(repair_db, verbose=False)
        storage_class, value = _row(repair_db, "/r/unset.jpg", "iso")
        assert storage_class == "null"
        assert value is None

    def test_a_second_run_reports_zero(self, repair_db):
        assert repair_integer_columns(repair_db, verbose=False) == 1
        assert repair_integer_columns(repair_db, verbose=False) == 0

    def test_a_check_violation_on_another_column_does_not_block_other_rows(self, repair_db):
        """A row can offend on more than one INTEGER column at once, and this
        repair batches all of a row's offending columns into a single UPDATE.
        SQLite only re-evaluates a CHECK constraint when a column it
        references is part of the UPDATE's SET list, so a row where a
        harmless `iso` and an out-of-range `star_rating` are BOTH REAL fails
        the whole per-row UPDATE (star_rating's CHECK still applies to itself
        after rounding, 12.7 -> 13, which is still > 5) -- neither column on
        that row is repaired, but this must not prevent the fix from still
        rounding an unrelated good row's `iso`.

        The seed value can only be written past the CHECK at all via
        ``PRAGMA ignore_check_constraints`` -- a real writer could never
        otherwise reach this state.
        """
        conn = sqlite3.connect(repair_db)
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(
            "INSERT INTO photos (path, filename, iso, star_rating) VALUES (?, ?, ?, ?)",
            ("/r/poisoned.jpg", "poisoned.jpg", 99.9, 12.7))
        conn.commit()
        conn.close()

        repaired = repair_integer_columns(repair_db, verbose=False)

        assert repaired == 1
        storage_class, value = _row(repair_db, "/r/fractional.jpg", "iso")
        assert storage_class == "integer"
        assert value == 63
        poisoned_iso_class, poisoned_iso = _row(repair_db, "/r/poisoned.jpg", "iso")
        assert poisoned_iso_class == "real"
        assert poisoned_iso == 99.9
        poisoned_star_class, poisoned_star = _row(repair_db, "/r/poisoned.jpg", "star_rating")
        assert poisoned_star_class == "real"
        assert poisoned_star == 12.7


def test_the_flag_takes_the_library_lock():
    from facet import LIBRARY_JOB_ARGS

    assert 'repair_int_columns' in LIBRARY_JOB_ARGS


def test_the_repair_covers_columns_other_than_iso_in_one_update(repair_db):
    """The column list is derived from `PHOTOS_COLUMNS` by SQLite's own
    affinity rule, not hand-written, because an `== 'INTEGER'` match would
    select nothing (the type strings are decorated: `'INTEGER DEFAULT 0
    CHECK (...)'`). Asserting that by re-deriving the list here would only
    restate the comprehension -- so this drives two *other* INTEGER columns
    through the job, on one row, and checks both come back repaired in the
    single UPDATE that row gets.
    """
    conn = sqlite3.connect(repair_db)
    conn.execute(
        "INSERT INTO photos (path, filename, face_count, image_width) VALUES (?, ?, ?, ?)",
        ("/r/other-columns.jpg", "other-columns.jpg", 2.4, 799.6))
    conn.commit()
    conn.close()

    assert repair_integer_columns(repair_db, verbose=False) == 2
    assert _row(repair_db, "/r/other-columns.jpg", "face_count") == ("integer", 2)
    assert _row(repair_db, "/r/other-columns.jpg", "image_width") == ("integer", 800)
    assert 'iso' in [name for name, coltype in PHOTOS_COLUMNS if 'INT' in coltype.upper()]
