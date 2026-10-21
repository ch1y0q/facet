"""Startup warning for an open install that may be reachable beyond loopback.

An empty ``viewer.password`` (the shipped default) is an "open install": every
request is served anonymously, including the library listing and ``/image``
originals. ``viewer.py`` binds ``0.0.0.0`` by default and the Docker image relies
on that, so the bind address is kept and the exposure is announced instead
(GHSA-vcrw-vgvh-gm76).

The decision is ``api.auth.open_install_exposure_warning``, a function of the bind
host and the auth module's own ``_is_open_install`` verdict, so it can never
disagree with what the server does for an anonymous caller. It is logged from
``create_app`` -- the one place every launch goes through, including
``uvicorn api:create_app --factory`` which never runs ``viewer.py`` -- and
``viewer.py`` only exports the address it binds for its children to read.
"""

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import api.auth as api_auth
import viewer
from api import BIND_HOST_ENV, CONFIGURE_LOGGING_ENV, create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPOSED_HOSTS = ["0.0.0.0", "::", "192.168.1.20", "2001:db8::1", "facet.example.com", "my-nas"]
LOOPBACK_HOSTS = ["127.0.0.1", "::1", "localhost", "LOCALHOST", "127.0.0.2", "::ffff:127.0.0.1"]
MARKER = "viewer.password is empty"


@pytest.fixture()
def auth_state():
    """Drive the verdict ``_is_open_install`` reads: the viewer block, the user
    store and the config-load flag, all on ``api.auth`` where it looks them up."""
    state = {"viewer": {"password": "", "edition_password": ""}, "multi_user": False, "load_failed": False}
    with (
        mock.patch.object(api_auth, "VIEWER_CONFIG", state["viewer"]),
        mock.patch.object(api_auth, "is_multi_user_enabled", lambda: state["multi_user"]),
        mock.patch.object(api_auth, "config_load_failed", lambda: state["load_failed"]),
    ):
        yield state


class TestOpenInstallExposureWarning:
    """Open install -> one line (host-specific when the bind host is a known
    non-loopback one, host-agnostic when unknown); loopback or locked -> None."""

    @pytest.mark.parametrize("host", EXPOSED_HOSTS)
    def test_known_exposed_host_gets_the_host_specific_line(self, auth_state, host):
        warning = api_auth.open_install_exposure_warning(host)
        assert warning is not None
        assert warning.startswith(f"{MARKER} and the viewer listens on ")
        assert "anyone who can reach this port can browse and download the whole library" in warning
        assert "\n" not in warning

    @pytest.mark.parametrize("unknown", [None, ""])
    def test_unknown_host_gets_the_host_agnostic_line(self, auth_state, unknown):
        warning = api_auth.open_install_exposure_warning(unknown)
        assert warning is not None
        assert warning.startswith(f"{MARKER}: anyone who can reach the viewer's port")
        assert "listens on" not in warning
        assert "\n" not in warning

    @pytest.mark.parametrize("host", [*EXPOSED_HOSTS, None])
    def test_both_lines_give_the_local_only_and_docker_advice(self, auth_state, host):
        warning = api_auth.open_install_exposure_warning(host)
        assert "Set viewer.password" in warning
        assert "--host 127.0.0.1" in warning
        assert "in Docker, publish the port as 127.0.0.1:5000:5000" in warning

    @pytest.mark.parametrize("host", LOOPBACK_HOSTS)
    def test_silent_on_a_known_loopback_bind(self, auth_state, host):
        assert api_auth.open_install_exposure_warning(host) is None

    @pytest.mark.parametrize("host", [*EXPOSED_HOSTS, *LOOPBACK_HOSTS, None])
    def test_silent_when_a_viewer_password_is_set(self, auth_state, host):
        auth_state["viewer"]["password"] = "s3cret"
        assert api_auth.open_install_exposure_warning(host) is None

    def test_an_edition_password_alone_does_not_lock_browsing(self, auth_state):
        auth_state["viewer"]["edition_password"] = "ed-pw"
        assert api_auth.open_install_exposure_warning("0.0.0.0") is not None

    @pytest.mark.parametrize("host", ["0.0.0.0", None])
    def test_silent_in_multi_user_mode(self, auth_state, host):
        auth_state["multi_user"] = True
        assert api_auth.open_install_exposure_warning(host) is None

    @pytest.mark.parametrize("host", ["0.0.0.0", None])
    def test_silent_when_the_config_failed_to_load(self, auth_state, host):
        auth_state["load_failed"] = True
        assert api_auth.open_install_exposure_warning(host) is None

    def test_names_the_address_that_is_exposed(self, auth_state):
        assert "listens on 192.168.1.20:" in api_auth.open_install_exposure_warning("192.168.1.20")

    def test_brackets_an_ipv6_address(self, auth_state):
        assert "listens on [::]:" in api_auth.open_install_exposure_warning("::")

    def test_carries_no_port(self, auth_state):
        # A port is not knowable from every launch; the message must not invent one.
        assert re.search(r"listens on 0\.0\.0\.0:\d", api_auth.open_install_exposure_warning("0.0.0.0")) is None

    def test_does_not_advertise_the_trusted_local_editing_opt_in(self, auth_state):
        assert "trusted_local_editing" not in api_auth.open_install_exposure_warning("0.0.0.0")


class TestCreateAppLogsTheWarning:
    """The factory logs it exactly once per app it builds, at WARNING, whatever
    launched it -- ``viewer.py`` (host exported) or uvicorn directly (it is not)."""

    @staticmethod
    def _warnings(caplog):
        return [r for r in caplog.records
                if r.levelno == logging.WARNING and MARKER in r.getMessage()]

    def test_open_install_logs_exactly_one_warning(self, auth_state, monkeypatch, caplog):
        monkeypatch.delenv(BIND_HOST_ENV, raising=False)
        with caplog.at_level(logging.WARNING):
            create_app()
        records = self._warnings(caplog)
        assert len(records) == 1
        assert records[0].name == "api"
        assert records[0].getMessage() == api_auth.open_install_exposure_warning(None)

    def test_the_exported_bind_host_makes_it_host_specific(self, auth_state, monkeypatch, caplog):
        monkeypatch.setenv(BIND_HOST_ENV, "0.0.0.0")
        with caplog.at_level(logging.WARNING):
            create_app()
        records = self._warnings(caplog)
        assert len(records) == 1
        assert "the viewer listens on 0.0.0.0:" in records[0].getMessage()

    def test_a_loopback_bind_logs_nothing(self, auth_state, monkeypatch, caplog):
        monkeypatch.setenv(BIND_HOST_ENV, "127.0.0.1")
        with caplog.at_level(logging.WARNING):
            create_app()
        assert self._warnings(caplog) == []

    @pytest.mark.parametrize("host", ["0.0.0.0", None])
    def test_a_viewer_password_logs_nothing(self, auth_state, monkeypatch, caplog, host):
        auth_state["viewer"]["password"] = "s3cret"
        if host is None:
            monkeypatch.delenv(BIND_HOST_ENV, raising=False)
        else:
            monkeypatch.setenv(BIND_HOST_ENV, host)
        with caplog.at_level(logging.WARNING):
            create_app()
        assert self._warnings(caplog) == []

    def test_each_app_built_logs_its_own_single_line(self, auth_state, monkeypatch, caplog):
        monkeypatch.delenv(BIND_HOST_ENV, raising=False)
        with caplog.at_level(logging.WARNING):
            create_app()
            create_app()
        assert len(self._warnings(caplog)) == 2


class TestViewerLauncher:
    """``viewer.py`` exports the address it binds and decides nothing itself."""

    @pytest.fixture()
    def run_main(self, monkeypatch):
        # main() exports both env flags for uvicorn's child processes; setting
        # them here makes monkeypatch restore the pre-test state at teardown.
        monkeypatch.setenv(CONFIGURE_LOGGING_ENV, "")
        monkeypatch.setenv(BIND_HOST_ENV, "")

        def _run(*argv):
            seen = {}
            monkeypatch.setattr(sys, "argv", ["viewer.py", "--production", *argv])
            with mock.patch(
                "uvicorn.run",
                side_effect=lambda *a, **k: seen.update(env=os.environ.get(BIND_HOST_ENV), kwargs=k),
            ):
                viewer.main()
            return seen

        return _run

    def test_exports_the_bind_host_before_uvicorn_starts(self, run_main):
        seen = run_main("--host", "10.1.2.3")
        assert seen["env"] == "10.1.2.3"
        assert seen["kwargs"]["host"] == "10.1.2.3"

    def test_default_host_is_still_all_interfaces_and_is_exported(self, run_main):
        seen = run_main()
        assert seen["kwargs"]["host"] == "0.0.0.0"
        assert seen["env"] == "0.0.0.0"

    def test_does_not_decide_or_log_the_warning_itself(self, run_main, auth_state, caplog):
        # The launcher must not run the decision (that is the factory's, once per worker):
        # an open install on all interfaces leaves no record from it, and the decision
        # function is never reached from main().
        with (
            mock.patch.object(api_auth, "open_install_exposure_warning", side_effect=AssertionError("called")),
            caplog.at_level(logging.WARNING),
        ):
            run_main("--host", "0.0.0.0")
        assert [r for r in caplog.records if MARKER in r.getMessage()] == []

    def test_launching_does_not_import_the_auth_or_config_modules(self):
        # In a fresh interpreter (this one has api.auth loaded by the suite): importing them
        # in the launcher re-runs the config bootstrap in the parent, so its warnings
        # double and --reload's parent dies on a broken config its child survives.
        script = (
            "import sys, types\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "sys.modules['uvicorn'] = types.SimpleNamespace(run=lambda *a, **k: None)\n"
            "sys.argv = ['viewer.py', '--production', '--host', '0.0.0.0']\n"
            "import viewer\n"
            "viewer.main()\n"
            "leaked = sorted(m for m in ('api.auth', 'api.config') if m in sys.modules)\n"
            "print('LEAKED=' + ','.join(leaked))\n"
        )
        done = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True,
                              cwd=REPO_ROOT, timeout=120)
        assert done.returncode == 0, done.stderr
        assert done.stdout.splitlines()[-1] == "LEAKED=", done.stdout
