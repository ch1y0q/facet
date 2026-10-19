"""Agent (MCP) bearer tokens: the service and the CRUD routes.

Every test runs on ``agent_app`` -- the real auth chain and the real lifespan --
because token liveness is decided by password generations and user records that a
``dependency_overrides`` client would never consult.
"""

import sqlite3
from datetime import timedelta

import pytest

from api import config as api_config
from api.agent import tokens
from api.auth import create_access_token, hash_password
from tests.conftest import _TEST_DB_FILE


def _rows():
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM mcp_tokens")]


def _mcp_claim_headers(sub, role="user", edition=False):
    return {"Authorization": "Bearer " + create_access_token(
        {"sub": sub, "role": role, "edition": edition, "mcp": True, "mcp_token_id": 1},
        expires_delta=timedelta(seconds=60))}


class TestTokenService:
    def test_mint_then_verify(self, agent_app):
        agent_app("legacy")
        row, plaintext = tokens.mint("_legacy", "laptop", "edition")
        assert plaintext.startswith("fct_") and len(plaintext) > 40
        grant = tokens.verify(plaintext)
        assert grant is not None and grant.id == row["id"] and grant.level == "edition"

    def test_only_hash_and_prefix_are_stored(self, agent_app):
        agent_app("legacy")
        row, plaintext = tokens.mint("_legacy", "laptop", "readonly")
        stored = _rows()
        assert len(stored) == 1
        assert all(plaintext not in str(v) for v in stored[0].values())
        assert stored[0]["token_hash"] != plaintext and len(stored[0]["token_hash"]) == 64
        assert plaintext.startswith(stored[0]["token_prefix"])
        assert "token" not in row and "token_hash" not in row

    def test_unknown_and_malformed_tokens_do_not_verify(self, agent_app):
        agent_app("legacy")
        assert tokens.verify("fct_nope") is None
        assert tokens.verify("") is None
        assert tokens.verify("not-a-token") is None

    def test_revoke_kills_the_token(self, agent_app):
        agent_app("legacy")
        row, plaintext = tokens.mint("_legacy", "laptop", "readonly")
        assert tokens.revoke(row["id"], "_legacy") is True
        assert tokens.verify(plaintext) is None
        assert tokens.revoke(row["id"], "_legacy") is False

    def test_level_check_constraint_rejects_junk(self, agent_app):
        agent_app("legacy")
        with pytest.raises(sqlite3.IntegrityError):
            with sqlite3.connect(_TEST_DB_FILE.name) as conn:
                conn.execute(
                    "INSERT INTO mcp_tokens (user_id, name, token_prefix, token_hash, level, "
                    "user_gen, created_at) VALUES ('u', 'n', 'p', 'h', 'root', 'g', 'now')")

    def test_legacy_edition_password_rotation_lowers_the_token(self, agent_app):
        agent_app("legacy")
        _, plaintext = tokens.mint("_legacy", "laptop", "edition")
        assert tokens.verify(plaintext).resolve().level == "edition"
        api_config.VIEWER_CONFIG["edition_password"] = "rotated"
        resolved = tokens.verify(plaintext).resolve()
        assert resolved is not None and resolved.level == "readonly"

    def test_legacy_edition_password_removed_lowers_the_token(self, agent_app):
        agent_app("legacy")
        _, plaintext = tokens.mint("_legacy", "laptop", "edition")
        api_config.VIEWER_CONFIG["edition_password"] = ""
        assert tokens.verify(plaintext).resolve().level == "readonly"

    def test_legacy_viewer_password_rotation_kills_the_token(self, agent_app):
        agent_app("legacy")
        _, plaintext = tokens.mint("_legacy", "laptop", "readonly")
        api_config.VIEWER_CONFIG["password"] = "rotated"
        assert tokens.verify(plaintext).resolve() is None

    def test_multi_user_password_change_kills_the_token(self, agent_app):
        agent_app("multi")
        _, plaintext = tokens.mint("alice", "laptop", "user")
        assert tokens.verify(plaintext).resolve().level == "user"
        api_config._FULL_CONFIG["users"]["alice"]["password_hash"] = hash_password("new")
        assert tokens.verify(plaintext).resolve() is None

    def test_multi_user_role_demotion_lowers_an_edition_token(self, agent_app):
        agent_app("multi")
        _, plaintext = tokens.mint("root", "laptop", "edition")
        assert tokens.verify(plaintext).resolve().level == "edition"
        api_config._FULL_CONFIG["users"]["root"]["role"] = "user"
        resolved = tokens.verify(plaintext).resolve()
        assert resolved.level == "user" and resolved.role == "user"

    def test_multi_user_promotion_never_raises_a_token(self, agent_app):
        agent_app("multi")
        _, plaintext = tokens.mint("alice", "laptop", "user")
        api_config._FULL_CONFIG["users"]["alice"]["role"] = "admin"
        assert tokens.verify(plaintext).resolve().level == "user"

    def test_multi_user_deleted_user_kills_the_token(self, agent_app):
        agent_app("multi")
        _, plaintext = tokens.mint("alice", "laptop", "user")
        del api_config._FULL_CONFIG["users"]["alice"]
        assert tokens.verify(plaintext).resolve() is None

    def test_a_token_never_outranks_its_minted_level(self, agent_app):
        agent_app("multi")
        _, plaintext = tokens.mint("root", "laptop", "readonly")
        assert tokens.verify(plaintext).resolve().level == "readonly"

    def test_open_install_is_always_readonly(self, agent_app):
        agent_app("open")
        _, plaintext = tokens.mint("_anonymous", "laptop", "edition")
        resolved = tokens.verify(plaintext).resolve()
        assert resolved.principal == "_anonymous" and resolved.level == "readonly"

    def test_open_install_token_dies_when_a_password_is_set(self, agent_app):
        agent_app("open")
        _, plaintext = tokens.mint("_anonymous", "laptop", "readonly")
        api_config.VIEWER_CONFIG["password"] = "now-locked"
        assert tokens.verify(plaintext).resolve() is None

    def test_failed_config_load_fails_closed(self, agent_app, monkeypatch):
        agent_app("open")
        _, plaintext = tokens.mint("_anonymous", "laptop", "readonly")
        monkeypatch.setattr("api.agent.tokens.config_load_failed", lambda: True)
        assert tokens.verify(plaintext).resolve() is None


class TestTokenRoutes:
    def test_flag_off_is_404_on_all_three_routes(self, agent_app):
        env = agent_app("multi", mcp_enabled=False)
        headers = env.login("alice")
        assert env.mint(headers).status_code == 404
        assert env.client.get("/api/mcp/tokens", headers=headers).status_code == 404
        assert env.client.delete("/api/mcp/tokens/1", headers=headers).status_code == 404

    def test_password_protected_install_refuses_a_cookie_only_post(self, agent_app):
        env = agent_app("legacy")
        resp = env.client.post("/api/auth/login", json={"password": "view-pw"})
        assert resp.status_code == 200 and env.client.cookies
        assert env.client.post("/api/mcp/tokens", json={"name": "x", "level": "readonly"}).status_code == 401

    def test_open_install_cookie_only_post_mints_a_readonly_token(self, agent_app):
        env = agent_app("open")
        resp = env.client.post("/api/mcp/tokens", json={"name": "x", "level": "edition"})
        assert resp.status_code == 200
        assert resp.json()["level"] == "readonly"

    def test_regular_user_cannot_mint_edition(self, agent_app):
        env = agent_app("multi")
        headers = env.login("alice")
        assert env.mint(headers, "edition").status_code == 403
        assert env.mint(headers, "user").status_code == 200
        assert env.mint(headers, "readonly").status_code == 200

    def test_admin_can_mint_edition(self, agent_app):
        env = agent_app("multi")
        resp = env.mint(env.login("root"), "edition")
        assert resp.status_code == 200 and resp.json()["level"] == "edition"

    def test_legacy_edition_session_mints_edition_and_plain_session_cannot(self, agent_app):
        env = agent_app("legacy")
        assert env.mint(env.login(), "edition").status_code == 403
        assert env.mint(env.login(edition=True), "edition").status_code == 200

    def test_legacy_user_level_is_capped_to_readonly(self, agent_app):
        env = agent_app("legacy")
        resp = env.mint(env.login(), "user")
        assert resp.status_code == 200 and resp.json()["level"] == "readonly"

    def test_unknown_level_is_422(self, agent_app):
        env = agent_app("multi")
        assert env.mint(env.login("alice"), "god").status_code == 422

    @pytest.mark.parametrize("mode,user", [("multi", "alice"), ("legacy", None)])
    def test_an_agent_credential_cannot_manage_tokens(self, agent_app, mode, user):
        env = agent_app(mode)
        sub = user or "_legacy"
        headers = _mcp_claim_headers(sub, edition=(mode == "legacy"))
        assert env.mint(headers, "readonly").status_code == 403
        assert env.client.get("/api/mcp/tokens", headers=headers).status_code == 403
        assert env.client.delete("/api/mcp/tokens/1", headers=headers).status_code == 403

    def test_plaintext_is_returned_once_and_never_listed(self, agent_app):
        env = agent_app("multi")
        headers = env.login("alice")
        created = env.mint(headers, "user", "laptop").json()
        assert created["token"].startswith("fct_")
        listed = env.client.get("/api/mcp/tokens", headers=headers)
        assert listed.status_code == 200
        body = listed.text
        assert created["token"] not in body and "token_hash" not in body
        item = listed.json()["tokens"][0]
        assert item["name"] == "laptop" and item["level"] == "user" and "token" not in item

    def test_list_is_own_only_and_superadmin_can_see_all(self, agent_app):
        env = agent_app("multi")
        api_config._FULL_CONFIG["users"]["boss"] = {
            "password_hash": hash_password("boss-pw"), "role": "superadmin", "directories": []}
        env.mint(env.login("alice"), "user", "a")
        env.mint(env.login("root"), "readonly", "r")
        boss = {"Authorization": "Bearer " + create_access_token(
            {"sub": "boss", "role": "superadmin", "edition": True})}
        alice_names = [t["name"] for t in env.client.get(
            "/api/mcp/tokens", headers=env.login("alice")).json()["tokens"]]
        assert alice_names == ["a"]
        assert env.client.get("/api/mcp/tokens?all=1", headers=env.login("alice")).status_code == 403
        everyone = env.client.get("/api/mcp/tokens?all=1", headers=boss).json()["tokens"]
        assert {t["name"] for t in everyone} == {"a", "r"}

    def test_revoke_own_token_only(self, agent_app):
        env = agent_app("multi")
        alice, bob = env.login("alice"), env.login("bob")
        token_id = env.mint(alice, "user").json()["id"]
        assert env.client.delete(f"/api/mcp/tokens/{token_id}", headers=bob).status_code == 404
        assert env.client.delete(f"/api/mcp/tokens/{token_id}", headers=alice).status_code == 200
        listed = env.client.get("/api/mcp/tokens", headers=alice).json()["tokens"]
        assert listed[0]["revoked"] == 1 and listed[0]["revoked_at"]

    def test_twenty_first_live_token_is_412(self, agent_app):
        env = agent_app("multi")
        headers = env.login("alice")
        for i in range(20):
            assert env.mint(headers, "readonly", f"t{i}").status_code == 200
        assert env.mint(headers, "readonly", "one-too-many").status_code == 412

    def test_revoked_tokens_do_not_count_toward_the_cap(self, agent_app):
        env = agent_app("multi")
        headers = env.login("alice")
        ids = [env.mint(headers, "readonly", f"t{i}").json()["id"] for i in range(20)]
        env.client.delete(f"/api/mcp/tokens/{ids[0]}", headers=headers)
        assert env.mint(headers, "readonly", "fresh").status_code == 200


class TestRevocationScope:
    def test_viewer_session_cannot_see_or_revoke_an_edition_token_in_single_password_mode(
            self, agent_app):
        env = agent_app("legacy")
        edition_session = env.login(edition=True)
        viewer_session = env.login()
        edition_id = env.mint(edition_session, "edition", "ed").json()["id"]
        readonly_id = env.mint(viewer_session, "readonly", "ro").json()["id"]
        seen = {t["id"] for t in env.client.get("/api/mcp/tokens", headers=viewer_session).json()["tokens"]}
        assert readonly_id in seen and edition_id not in seen
        assert env.client.delete(f"/api/mcp/tokens/{edition_id}", headers=viewer_session).status_code == 403
        assert tokens.verify(env.token(edition_session, "edition", "ed2")) is not None
        assert {t["id"] for t in env.client.get(
            "/api/mcp/tokens", headers=edition_session).json()["tokens"]} >= {edition_id, readonly_id}
        assert env.client.delete(f"/api/mcp/tokens/{edition_id}", headers=edition_session).status_code == 200
        assert env.client.delete(f"/api/mcp/tokens/{readonly_id}", headers=viewer_session).status_code == 200
