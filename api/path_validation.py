"""Shared filesystem path validation for photo file access.

Resolves a database photo path to a real on-disk path and enforces that it
stays within the configured scan directories. This is defense-in-depth against
path traversal and symlink escape: callers must already have confirmed the
``db_path`` exists in the database and is visible to the requesting user (via
the visibility clause), but the mapped disk path is still canonicalised and
checked against the scan-directory allowlist before any file is opened.

The allowlist is enforced whenever scan directories are configured (always in
multi-user mode, fail-closed; and in single-user mode when ``path_mapping`` or
user directories are set). Pure-local single-user installs expose no
configurable root, so there the database-membership check performed by callers
is the containment boundary.
"""

import os

from fastapi import HTTPException

from api.config import (
    get_all_scan_directories,
    is_multi_user_enabled,
    map_disk_path,
)


class PhotoFileMissing(HTTPException):
    """The 404 for a path that passed containment but has no file on disk.

    A subclass, so every caller catching ``HTTPException`` is unaffected; the
    one that must tell "gone" apart from "refused by the allowlist" catches
    this first. ``real_path`` is the canonical path the file was expected at.
    """

    def __init__(self, real_path: str):
        super().__init__(status_code=404, detail='File not found on disk')
        self.real_path = real_path


def resolve_photo_disk_path(db_path: str) -> str:
    """Resolve a DB-validated photo path to a real disk path within scan dirs.

    Args:
        db_path: A photo path already confirmed to exist in the database and
            be visible to the current user.

    Returns:
        The canonical real disk path, guaranteed to exist on disk and, when
        scan directories are configured, to live under an allowed one.

    Raises:
        HTTPException: 404 if the resolved path escapes the scan-directory
            allowlist or the file is missing on disk.
    """
    disk_path = map_disk_path(db_path)
    real_disk = os.path.realpath(disk_path)
    scan_dirs = get_all_scan_directories()
    if is_multi_user_enabled() or scan_dirs:
        if not any(
            real_disk.startswith(os.path.realpath(d) + os.sep)
            for d in scan_dirs
        ):
            raise HTTPException(status_code=404, detail='File not found')
    if not os.path.isfile(real_disk):
        raise PhotoFileMissing(real_disk)
    return real_disk
