"""Config and install predicates that gate a tool, beside its level (see ``tools_common.tool_refusal``).

A predicate answers ``None`` (available) or ``(code, message)``. ``feature_disabled`` is for an
operator's configuration (a flag that is off); ``forbidden_level`` stays for the grant. Every
predicate is a pure function of the resolved grant and the request's ``mcp_settings()`` snapshot
(plus live config where the route reads the same), so the list hook and the call wrapper agree.
"""

from typing import Any, Optional

from api.auth import EDITION_PASSWORD_KEY, _is_open_install, scan_access_refusal
from api.config import VIEWER_CONFIG, is_multi_user_enabled

DESTRUCTIVE_KEY = "viewer.mcp.allow_destructive"
SCAN_KEY = "viewer.features.show_scan_button"


def destructive_allowed(resolved: Any, settings: dict) -> Optional[tuple[str, str]]:
    if settings.get("allow_destructive"):
        return None
    return ("feature_disabled",
            f"Destructive actions are off for assistants: the operator must set {DESTRUCTIVE_KEY} to true. "
            "Nothing was done")


def scan_available(resolved: Any, settings: dict) -> Optional[tuple[str, str]]:
    """The scan route's own rule: the feature flag, then ``scan_access_refusal`` (shared with the route).

    Both are waived for a grant whose /mcp request passed the trusted-local boundary
    (``resolved.local_trusted``), exactly as the route waives them for ``user.trusted_local_editing``.
    """
    local = bool(resolved.local_trusted)
    if not local and not VIEWER_CONFIG.get("features", {}).get("show_scan_button", False):
        return "feature_disabled", f"Scanning is off: the operator must set {SCAN_KEY} to true"
    refusal = scan_access_refusal(
        is_multi_user_enabled(), resolved.role == "superadmin", resolved.level == "edition",
        _is_open_install(EDITION_PASSWORD_KEY), local)
    return None if refusal is None else ("forbidden_level", refusal[1])
