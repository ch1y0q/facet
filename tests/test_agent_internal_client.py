"""The internal ASGI client: allowlist, grant enforcement, JWT, status mapping, caps."""

import asyncio
import dataclasses
import json
from datetime import timedelta
from types import MappingProxyType

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from api import config as api_config
from api.agent import limits, tokens
from api.agent.internal_client import (
    ROUTE_ALLOWLIST, InternalClient, NotAllowedError, RouteSpec,
)
from api.auth import decode_access_token
from tests.conftest import AGENT_DIR

PHOTO = AGENT_DIR + "fav.jpg"
READ_ROUTE = RouteSpec("GET", "/api/photo", "readonly")
RATE_ROUTE = RouteSpec("POST", "/api/photo/toggle_favorite", "user", write=True)
# Deliberately mislabelled: an edition-only route declared as readonly, so the only
# thing standing between the token and the route is the JWT the client mints.
MISLABELLED_EDITION_ROUTE = RouteSpec("POST", "/api/photos/batch_reject", "readonly", write=True)


class CountingApp:
    """ASGI wrapper counting how many requests reached the app."""

    def __init__(self, app):
        self.app = app
        self.hits = 0

    async def __call__(self, scope, receive, send):
        self.hits += 1
        await self.app(scope, receive, send)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def photo(seed_photos_prefix):
    seed_photos_prefix(AGENT_DIR, [{"path": PHOTO, "filename": "fav.jpg", "aggregate": 7.0}])
    return PHOTO


def _client(env, **allow):
    counting = CountingApp(env.app)
    return InternalClient(counting, allowlist={**allow}), counting


class TestLocalEditionGrant:
    """An open-install edition token that the /mcp boundary judged local (``trusted_local``)."""

    @staticmethod
    def _local_grant(env, trusted):
        api_config.VIEWER_CONFIG["trusted_local_editing"] = True
        _, plaintext = tokens.mint("_anonymous", "laptop", "edition", "edition")
        return dataclasses.replace(tokens.verify(plaintext), trusted_local=trusted)

    def test_local_edition_grant_reaches_edition_route(self, agent_app, photo):
        env = agent_app("open")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(self._local_grant(env, True), "rate", json={"photo_path": photo}))
        assert result["ok"] is True, result
        assert counting.hits == 1

    def test_send_takes_the_fact_from_the_grant_it_is_handed(self, agent_app, photo):
        # REGRESSION GUARD: the same token WITHOUT the fact stays readonly, the route is never reached.
        env = agent_app("open")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(self._local_grant(env, False), "rate", json={"photo_path": photo}))
        assert result["error"] == "forbidden_level" and counting.hits == 0

    def test_the_signed_claims_name_the_local_edition_grant_only(self, agent_app):
        env = agent_app("open")
        claims = self._local_grant(env, True).resolve().jwt_claims()
        assert claims is not None and "sub" not in claims and claims["edition"] is True
        assert claims["mcp"] is True and claims["mcp_local"] is True
        # REGRESSION GUARD: an untrusted edition token and a readonly one still send no credential.
        assert self._local_grant(env, False).resolve().jwt_claims() is None
        _, readonly = tokens.mint("_anonymous", "ro", "readonly", "edition")
        assert dataclasses.replace(tokens.verify(readonly), trusted_local=True).resolve().jwt_claims() is None

    def test_the_opt_in_going_off_inside_the_jwt_lifetime_refuses(self, agent_app, photo):
        env = agent_app("open")
        resolved_claims = self._local_grant(env, True).resolve().jwt_claims()
        assert resolved_claims is not None
        api_config.VIEWER_CONFIG["trusted_local_editing"] = False
        from api.auth import create_access_token
        jwt_str = create_access_token(resolved_claims, expires_delta=timedelta(seconds=60))
        probe = TestClient(env.app, base_url="http://facet.internal", client=("127.0.0.1", 0))
        refused = probe.post("/api/photo/toggle_favorite", json={"photo_path": photo},
                             headers={"Authorization": "Bearer " + jwt_str})
        assert refused.status_code == 403


class TestAllowlist:
    # Edition-only READS the allowlist carries on purpose (the routes themselves are edition-gated), and the
    # only /api/scan and /api/config routes it may name.
    EDITION_READS = ("/api/comparison/stats", "/api/comparison/coverage", "/api/scan/status", "/api/scan/directories")
    ALLOWED_PREFIXED = ("/api/scan/start", "/api/scan/status", "/api/scan/directories", "/api/config/scoring_contexts")

    def test_allowlist_is_frozen_and_only_writes_demand_a_level(self):
        assert isinstance(ROUTE_ALLOWLIST, MappingProxyType)
        assert all(spec.min_level == "readonly" or spec.write or spec.template.endswith("/api/cull/apply")
                   or spec.template.endswith("/api/photo/delete") or spec.template in self.EDITION_READS
                   for spec in ROUTE_ALLOWLIST.values())
        assert all(spec.min_level != "readonly" for spec in ROUTE_ALLOWLIST.values() if spec.write)
        assert not any(spec.template.startswith(("/api/admin", "/api/config", "/api/scan",
                                                 "/api/auth", "/dav", "/api/frame"))
                       and spec.template not in self.ALLOWED_PREFIXED
                       for spec in ROUTE_ALLOWLIST.values())

    def test_unknown_tool_raises_without_an_upstream_call(self, agent_app):
        env = agent_app("legacy")
        token = env.token(env.login())
        client, counting = _client(env, get_photo=READ_ROUTE)
        with pytest.raises(NotAllowedError):
            _run(client.call(tokens.verify(token), "scan_library"))
        assert counting.hits == 0


class TestGrantEnforcement:
    def test_readonly_token_of_an_admin_is_refused_before_any_upstream_call(self, agent_app, photo):
        env = agent_app("multi")
        token = env.token(env.login("root"), "readonly")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(tokens.verify(token), "rate", json={"photo_path": photo}))
        assert result["ok"] is False and result["error"] == "forbidden_level"
        assert counting.hits == 0

    def test_user_token_cannot_reach_an_edition_route(self, agent_app, photo):
        env = agent_app("multi")
        token = env.token(env.login("alice"), "user")
        edition_route = RouteSpec("POST", "/api/photos/batch_reject", "edition", write=True)
        client, counting = _client(env, reject=edition_route)
        result = _run(client.call(tokens.verify(token), "reject", json={"photo_paths": [photo]}))
        assert result["error"] == "forbidden_level" and counting.hits == 0

    def test_user_token_reaches_a_user_route(self, agent_app, photo):
        env = agent_app("multi")
        token = env.token(env.login("alice"), "user")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(tokens.verify(token), "rate", json={"photo_path": photo}))
        assert result["ok"] is True, result
        assert counting.hits == 1

    def test_jwt_of_a_readonly_admin_token_carries_no_admin_rights(self, agent_app):
        env = agent_app("multi")
        token = env.token(env.login("root"), "readonly")
        claims = tokens.verify(token).resolve().jwt_claims()
        assert claims["role"] == "user" and claims["edition"] is False and claims["mcp"] is True
        assert claims["sub"] == "root"

    def test_jwt_of_an_edition_admin_token_keeps_the_live_role(self, agent_app):
        env = agent_app("multi")
        token = env.token(env.login("root"), "edition")
        claims = tokens.verify(token).resolve().jwt_claims()
        assert claims["role"] == "admin" and claims["edition"] is True

    def test_jwt_is_short_lived_and_decodes_against_current_generations(self, agent_app):
        env = agent_app("legacy")
        token = env.token(env.login(edition=True), "edition")
        resolved = tokens.verify(token).resolve()
        from api.auth import create_access_token
        jwt_str = create_access_token(resolved.jwt_claims(), expires_delta=timedelta(seconds=60))
        payload = decode_access_token(jwt_str)
        assert payload["mcp"] is True and payload["mcp_token_id"] == resolved.token_id
        assert payload["exp"] - payload["iat"] <= 60
        assert payload["edition"] is True

    def test_admin_readonly_token_is_refused_by_the_route_itself(self, agent_app, photo):
        """Defence in depth: even a mislabelled route is closed by the role-matching JWT."""
        env = agent_app("multi")
        token = env.token(env.login("root"), "readonly")
        client, counting = _client(env, reject=MISLABELLED_EDITION_ROUTE)
        result = _run(client.call(tokens.verify(token), "reject", json={"photo_paths": [photo]}))
        assert counting.hits == 1
        assert result["ok"] is False and result["error"] == "forbidden_level"

    def test_legacy_readonly_token_cannot_ride_a_rating_route(self, agent_app, photo):
        env = agent_app("legacy")
        token = env.token(env.login(), "readonly")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(tokens.verify(token), "rate", json={"photo_path": photo}))
        assert result["error"] == "forbidden_level" and counting.hits == 0

    def test_open_install_sends_no_authorization_header(self, agent_app):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        assert tokens.verify(token).resolve().jwt_claims() is None

    def test_dead_token_is_forbidden_at_call_time(self, agent_app):
        env = agent_app("legacy")
        token = env.token(env.login(), "readonly")
        grant = tokens.verify(token)
        api_config.VIEWER_CONFIG["password"] = "rotated"
        client, counting = _client(env, get=READ_ROUTE)
        result = _run(client.call(grant, "get", query={"path": "x"}))
        assert result["error"] == "forbidden_level" and counting.hits == 0


def _fake_app():
    app = FastAPI()

    @app.get("/s/{code}")
    async def status(code: int):
        if code == 503:
            return JSONResponse({"detail": "library busy"}, status_code=503)
        raise HTTPException(status_code=code, detail=f"detail {code}")

    @app.get("/config403/{detail}")
    async def config_refusal(detail: str):
        raise HTTPException(status_code=403, detail=detail)

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(2)
        return {}

    @app.post("/slow")
    async def slow_write():
        await asyncio.sleep(2)
        return {}

    @app.get("/big")
    async def big():
        return {"rows": [{"path": f"/p/{i}", "caption": "x" * 200} for i in range(500)], "total": 500}

    return app


class TestStatusMapping:
    @pytest.mark.parametrize("code,expected", [
        (401, "forbidden_level"), (403, "forbidden_level"), (404, "not_found"),
        (400, "invalid_input"), (412, "invalid_input"), (422, "invalid_input"),
        (409, "conflict"), (429, "rate_limited"), (503, "library_busy"), (500, "upstream_error"),
    ])
    def test_error_codes(self, agent_app, code, expected):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"s": RouteSpec("GET", "/s/{code}", "readonly")})
        result = _run(client.call(tokens.verify(token), "s", path_args={"code": code}))
        assert result["ok"] is False and result["error"] == expected

    @pytest.mark.parametrize("detail,expected", [
        ("Scan feature not enabled", "feature_disabled"), ("OS-trash is disabled", "feature_disabled"),
        ("Set viewer.edition_password to enable the scan trigger", "feature_disabled"),
        ("Edition access required", "forbidden_level"),
    ])
    def test_a_403_that_names_a_config_switch_is_feature_disabled(self, agent_app, detail, expected):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"c": RouteSpec("GET", "/config403/{detail}", "readonly")})
        result = _run(client.call(tokens.verify(token), "c", path_args={"detail": detail}))
        assert result["error"] == expected

    def test_read_timeout_is_upstream_error(self, agent_app):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"slow": RouteSpec("GET", "/slow", "readonly")})
        result = _run(client.call(tokens.verify(token), "slow", timeout=0.05))
        assert result["error"] == "upstream_error"

    def test_timeout_does_not_need_asyncio_timeout_python_3_11(self, agent_app, monkeypatch):
        monkeypatch.delattr(asyncio, "timeout")
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"slow": RouteSpec("GET", "/slow", "readonly")})
        result = _run(client.call(tokens.verify(token), "slow", timeout=0.05))
        assert result["error"] == "upstream_error"
        assert "did not answer in time" in result["message"]

    def test_write_timeout_is_outcome_unknown(self, agent_app):
        env = agent_app("legacy")
        token = env.token(env.login(edition=True), "edition")
        client = InternalClient(_fake_app(), allowlist={
            "slow": RouteSpec("POST", "/slow", "edition", write=True)})
        result = _run(client.call(tokens.verify(token), "slow", timeout=0.05, json={}))
        assert result["error"] == "outcome_unknown"
        assert "do not blindly retry" in result["message"]

    def test_success_returns_the_parsed_body(self, agent_app):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"big": RouteSpec("GET", "/big", "readonly")})
        result = _run(client.call(tokens.verify(token), "big"))
        assert result["ok"] is True and result["data"]["total"] == 500


class TestCaps:
    def test_over_cap_envelope_is_truncated_and_valid_json(self):
        envelope = {"ok": True, "data": {"rows": [{"path": f"/p/{i}", "caption": "x" * 200}
                                                  for i in range(500)], "total": 500}}
        capped = limits.fit_envelope(envelope, max_rows=100, max_bytes=20000)
        encoded = json.dumps(capped, separators=(",", ":"))
        assert len(encoded.encode()) <= 20000
        assert capped["truncated"] is True and len(capped["data"]["rows"]) < 100
        assert capped["data"]["total"] == 500
        assert json.loads(encoded) == capped

    def test_under_cap_envelope_is_untouched(self):
        envelope = {"ok": True, "data": {"rows": [{"path": "/a"}], "total": 1}}
        assert limits.fit_envelope(envelope, max_rows=100, max_bytes=20000) == envelope

    def test_row_cap_alone_truncates(self):
        envelope = {"ok": True, "data": {"rows": [{"p": i} for i in range(150)]}}
        capped = limits.fit_envelope(envelope, max_rows=100, max_bytes=500000)
        assert capped["truncated"] is True and len(capped["data"]["rows"]) == 100


class TestPathArgs:
    @pytest.mark.parametrize("value", ["..", ".", "", "../x", "a/../b", "./x"])
    def test_dot_segments_and_empty_path_args_are_refused_before_any_upstream_call(self, agent_app, value):
        env = agent_app("open")
        grant = tokens.verify(env.token(env.login(), "readonly"))
        counting = CountingApp(FastAPI())
        client = InternalClient(counting, allowlist=MappingProxyType(
            {"sim": RouteSpec("GET", "/api/similar_photos/{path}", "readonly")}))
        result = _run(client.call(grant, "sim", path_args={"path": value}))
        assert result["ok"] is False and result["error"] == "invalid_input" and counting.hits == 0

    def test_similar_photos_tool_refuses_dot_dot(self, agent_app):
        env = agent_app("open")
        token = env.token(env.login())
        result = env.call(token, "similar_photos", {"path": ".."})
        assert result["ok"] is False and result["error"] == "invalid_input"
