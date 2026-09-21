"""Tests for the sqlite-vec availability probe in ``db.connection``.

The probe must answer "importable *and* loadable", not just "importable": a
pyenv / system Python whose bundled SQLite was built without extension loading
can still ``import sqlite_vec`` while every connection then raises
``AttributeError: 'sqlite3.Connection' object has no attribute
'enable_load_extension'``. Treating that as available made the viewer log a
traceback on every async request instead of using the NumPy search fallback.
"""

import sys
from unittest import mock

import db.connection as conn


def test_probe_returns_bool():
    assert isinstance(conn._probe_sqlite_vec(), bool)


def test_probe_false_when_import_fails():
    """A missing sqlite_vec package is reported False, never raised.

    A ``None`` entry in ``sys.modules`` makes the ``import`` statement raise
    ImportError, exactly as if the package were not installed.
    """
    with mock.patch.dict(sys.modules, {"sqlite_vec": None}):
        assert conn._probe_sqlite_vec() is False


def test_probe_false_when_extension_loading_unavailable():
    """Importable sqlite_vec + a sqlite3 that cannot load extensions -> False.

    Reproduces the macOS pyenv build: the import succeeds but the connection
    object has no ``enable_load_extension``. The throwaway probe connection is
    still closed via the finally block.
    """
    fake_sqlite_vec = mock.MagicMock()
    fake_conn = mock.MagicMock()
    del fake_conn.enable_load_extension  # accessing it now raises AttributeError

    with mock.patch.dict(sys.modules, {"sqlite_vec": fake_sqlite_vec}), \
            mock.patch.object(conn.sqlite3, "connect", return_value=fake_conn):
        assert conn._probe_sqlite_vec() is False

    fake_conn.close.assert_called_once()


def test_probe_true_when_extension_loads():
    """An importable package whose extension loads on a probe connection -> True."""
    fake_sqlite_vec = mock.MagicMock()
    fake_conn = mock.MagicMock()

    with mock.patch.dict(sys.modules, {"sqlite_vec": fake_sqlite_vec}), \
            mock.patch.object(conn.sqlite3, "connect", return_value=fake_conn):
        assert conn._probe_sqlite_vec() is True

    fake_conn.enable_load_extension.assert_called_once_with(True)
    fake_sqlite_vec.load.assert_called_once_with(fake_conn)
    fake_conn.close.assert_called_once()
