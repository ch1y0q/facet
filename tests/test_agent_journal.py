"""The undo journal: what each write records, what ``undo_last`` restores, and what it refuses to touch.

[REAL] ``agent_app`` (real auth chain), real routes, rows seeded into the shared session DB; the journal
table is read straight from SQLite to see what the wrapper recorded. A human edit is made through the
real UI route with a real session bearer.
"""

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from api.agent import journal
from db.schema import AGENT_ACTIONS_COLUMNS, init_database
from tests.conftest import _TEST_DB_FILE, AGENT_DIR

PREFIX = AGENT_DIR + "journal/"
P = [PREFIX + f"j{i}.jpg" for i in range(4)]
ROWS = [{"path": p, "filename": p.rsplit("/", 1)[1], "aggregate": 6.0, "star_rating": 1} for p in P]
GAP = "journal-unit-owner"


def db(sql, *args):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute(sql, args).fetchall()


def photo(path):
    return db("SELECT star_rating, is_favorite, is_rejected FROM photos WHERE path = ?", path)[0]


def journal_rows(tool=None):
    sql, args = "SELECT target_key, field, old_value, new_value, undone_at FROM agent_actions", ()
    if tool:
        sql, args = sql + " WHERE tool = ?", (tool,)
    return db(sql + " ORDER BY id", *args)


@pytest.fixture()
def world(agent_app, seed_photos_prefix):
    seed_photos_prefix(PREFIX, ROWS)
    db("DELETE FROM agent_actions")
    env = agent_app("legacy")
    yield env, env.token(env.login(edition=True), "edition")
    db("DELETE FROM agent_actions")
    db("DELETE FROM photo_manual_tags WHERE photo_path LIKE ?", PREFIX + "%")
    db("DELETE FROM album_photos WHERE photo_path LIKE ?", PREFIX + "%")
    db("DELETE FROM user_preferences WHERE photo_path LIKE ?", PREFIX + "%")


def ui_rate(env, path, rating):
    resp = env.client.post("/api/photo/set_rating", json={"photo_path": path, "rating": rating},
                           headers=env.login(edition=True))
    assert resp.status_code == 200, resp.text


class TestRatings:
    def test_set_rating_journals_one_row_per_changed_photo_and_none_for_already(self, world):
        env, token = world
        first = env.call(token, "set_rating", {"paths": [P[0], P[1]], "rating": 4})
        assert first["ok"] and first["data"]["undo"]["available"] is True
        env.call(token, "set_rating", {"paths": [P[2]], "rating": 1})
        assert {r[0] for r in journal_rows("set_rating")} == {P[0], P[1]}
        count = len(journal_rows())
        again = env.call(token, "set_rating", {"paths": [P[0], P[1]], "rating": 4})
        assert "undo" not in again["data"] and len(journal_rows()) == count

    def test_new_value_is_the_intended_one(self, world):
        env, token = world
        env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})
        assert ("star_rating", "1", "4") in {(r[1], r[2], r[3]) for r in journal_rows()}

    def test_set_rejected_journals_rating_and_favorite_side_effects(self, world):
        env, token = world
        env.call(token, "set_favorite", {"paths": [P[0]], "value": True})
        env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})
        db("DELETE FROM agent_actions")
        env.call(token, "set_rejected", {"paths": [P[0]], "value": True})
        assert {r[1] for r in journal_rows()} == {"star_rating", "is_favorite", "is_rejected"}
        assert photo(P[0]) == (0, 0, 1)

    def test_undo_restores_rating_and_favorite_after_reject(self, world):
        env, token = world
        env.call(token, "set_favorite", {"paths": [P[0]], "value": True})
        env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})
        rejected = env.call(token, "set_rejected", {"paths": [P[0]], "value": True})
        undone = env.call(token, "undo_last", {"batch_id": rejected["data"]["undo"]["batch_id"]})
        assert undone["data"]["outcomes"] == {"restored": 1}, undone
        assert photo(P[0]) == (4, 1, 0)

    def test_undo_refuses_row_changed_by_user_after_agent(self, world):
        env, token = world
        batch = env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})["data"]["undo"]["batch_id"]
        ui_rate(env, P[0], 2)
        undone = env.call(token, "undo_last", {"batch_id": batch})
        assert undone["data"]["outcomes"] == {"skipped_changed_since": 1}
        assert photo(P[0])[0] == 2

    def test_undo_flags_tuple_is_all_or_nothing(self, world):
        env, token = world
        env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})
        batch = env.call(token, "set_rejected", {"paths": [P[0]], "value": True})["data"]["undo"]["batch_id"]
        ui_rate(env, P[0], 2)
        before = photo(P[0])
        undone = env.call(token, "undo_last", {"batch_id": batch})
        assert undone["data"]["outcomes"] == {"skipped_changed_since": 1} and photo(P[0]) == before

    def test_null_and_zero_flags_compare_equal(self, world):
        env, token = world
        db("UPDATE photos SET is_favorite = NULL, is_rejected = NULL WHERE path = ?", P[0])
        batch = env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})["data"]["undo"]["batch_id"]
        assert env.call(token, "undo_last", {"batch_id": batch})["data"]["outcomes"] == {"restored": 1}
        assert photo(P[0])[0] == 1

    def test_ui_edit_is_not_journaled(self, world):
        env, _ = world
        ui_rate(env, P[0], 3)
        assert journal_rows() == []

    def test_undo_twice_is_already_undone(self, world):
        env, token = world
        batch = env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})["data"]["undo"]["batch_id"]
        assert env.call(token, "undo_last", {"batch_id": batch})["ok"]
        assert env.call(token, "undo_last", {"batch_id": batch})["error"] == "already_undone"
        assert all(r[4] is not None for r in journal_rows())

    def test_undo_missing_photo_is_reported_missing(self, world):
        env, token = world
        batch = env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})["data"]["undo"]["batch_id"]
        db("DELETE FROM photos WHERE path = ?", P[0])
        undone = env.call(token, "undo_last", {"batch_id": batch})
        assert undone["data"]["outcomes"] == {"missing": 1}

    def test_undo_with_nothing_to_undo_says_so(self, world):
        env, token = world
        data = env.call(token, "undo_last", {})["data"]
        assert data["batch_id"] is None and data["note"] == "Nothing to undo"

    def test_dry_run_reports_the_batch_and_changes_nothing(self, world):
        env, token = world
        batch = env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})["data"]["undo"]["batch_id"]
        dry = env.call(token, "undo_last", {"batch_id": batch, "dry_run": True})["data"]
        assert dry["dry_run"] is True and dry["tool"] == "set_rating" and dry["targets"] == [P[0]]
        assert photo(P[0])[0] == 4 and all(r[4] is None for r in journal_rows())

    def test_default_undo_targets_the_latest_open_batch(self, world):
        env, token = world
        env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})
        env.call(token, "set_rating", {"paths": [P[1]], "rating": 5})
        env.call(token, "undo_last", {})
        assert photo(P[1])[0] == 1 and photo(P[0])[0] == 4

    def test_list_agent_actions_groups_batches_without_values(self, world):
        env, token = world
        env.call(token, "set_rating", {"paths": [P[0], P[1]], "rating": 4})
        rows = env.call(token, "list_agent_actions", {})["data"]["rows"]
        assert len(rows) == 1 and rows[0]["tool"] == "set_rating" and rows[0]["rows"] == 6
        assert rows[0]["undone"] is False and "old_value" not in rows[0] and "new_value" not in rows[0]
        env.call(token, "undo_last", {})
        assert env.call(token, "list_agent_actions", {})["data"]["rows"] == []
        assert len(env.call(token, "list_agent_actions", {"include_undone": True})["data"]["rows"]) == 1


class TestOtherFields:
    def test_manual_tags_and_album_roundtrip(self, world):
        env, token = world
        tagged = env.call(token, "add_tags", {"tags": ["jtag"], "paths": [P[0]]})
        assert tagged["ok"], tagged
        assert ("manual_tag:jtag" in {r[1] for r in journal_rows()})
        env.call(token, "undo_last", {"batch_id": tagged["data"]["undo"]["batch_id"]})
        assert db("SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path = ?", P[0]) == [(0,)]
        album = env.call(token, "create_album", {"name": "journal-album"})["data"]
        try:
            added = env.call(token, "album_add_photos", {"album_id": album["id"], "paths": [P[0], P[1]]})
            assert added["ok"] and added["data"]["undo"]["rows"] == 2
            assert db("SELECT COUNT(*) FROM album_photos WHERE album_id = ?", album["id"]) == [(2,)]
            env.call(token, "undo_last", {"batch_id": added["data"]["undo"]["batch_id"]})
            assert db("SELECT COUNT(*) FROM album_photos WHERE album_id = ?", album["id"]) == [(0,)]
        finally:
            db("DELETE FROM album_photos WHERE album_id = ?", album["id"])
            db("DELETE FROM albums WHERE id = ?", album["id"])

    def test_create_album_is_not_journaled(self, world):
        env, token = world
        album = env.call(token, "create_album", {"name": "journal-album-2"})["data"]
        try:
            assert journal_rows("create_album") == []
        finally:
            db("DELETE FROM albums WHERE id = ?", album["id"])

    def test_caption_roundtrip(self, world):
        env, token = world
        batch = env.call(token, "set_caption", {"path": P[0], "caption": "agent words"})["data"]["undo"]["batch_id"]
        assert db("SELECT caption FROM photos WHERE path = ?", P[0]) == [("agent words",)]
        assert env.call(token, "undo_last", {"batch_id": batch})["data"]["outcomes"] == {"restored": 1}
        assert db("SELECT caption FROM photos WHERE path = ?", P[0])[0][0] in (None, "")


class TestOwners:
    def test_multi_user_rating_undo_writes_user_preferences_not_photos(self, agent_app, seed_photos_prefix):
        seed_photos_prefix(PREFIX, ROWS)
        db("DELETE FROM agent_actions")
        env = agent_app("multi")
        token = env.token(env.login("alice"), "user")
        before = photo(P[0])
        batch = env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})["data"]["undo"]["batch_id"]
        assert photo(P[0]) == before
        assert db("SELECT star_rating FROM user_preferences WHERE user_id = 'alice' AND photo_path = ?", P[0]) == [(5,)]
        assert env.call(token, "undo_last", {"batch_id": batch})["data"]["outcomes"] == {"restored": 1}
        assert photo(P[0]) == before
        assert db("SELECT star_rating FROM user_preferences WHERE user_id = 'alice' AND photo_path = ?",
                  P[0])[0][0] in (0, None)
        db("DELETE FROM agent_actions")
        db("DELETE FROM user_preferences WHERE photo_path LIKE ?", PREFIX + "%")

    def test_undo_other_owner_is_not_found_and_changes_nothing(self, agent_app, seed_photos_prefix):
        seed_photos_prefix(PREFIX, ROWS)
        db("DELETE FROM agent_actions")
        env = agent_app("multi")
        alice = env.token(env.login("alice"), "user")
        batch = env.call(alice, "set_rating", {"paths": [P[0]], "rating": 5})["data"]["undo"]["batch_id"]
        bob = env.token(env.login("bob"), "user")
        assert env.call(bob, "undo_last", {"batch_id": batch})["error"] == "not_found"
        assert env.call(bob, "list_agent_actions", {})["data"]["rows"] == []
        assert len(env.call(alice, "list_agent_actions", {})["data"]["rows"]) == 1
        assert all(r[4] is None for r in journal_rows())
        db("DELETE FROM agent_actions")
        db("DELETE FROM user_preferences WHERE photo_path LIKE ?", PREFIX + "%")

    def test_a_readonly_key_cannot_undo(self, world):
        env, token = world
        batch = env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})["data"]["undo"]["batch_id"]
        readonly = env.token(env.login(), "readonly")
        assert env.call(readonly, "undo_last", {"batch_id": batch})["error"] == "forbidden_level"
        assert photo(P[0])[0] == 4


class TestRestRoutes:
    def test_list_is_owner_scoped_and_agent_tokens_are_refused(self, agent_app, seed_photos_prefix):
        seed_photos_prefix(PREFIX, ROWS)
        db("DELETE FROM agent_actions")
        env = agent_app("multi")
        alice = env.token(env.login("alice"), "user")
        env.call(alice, "set_rating", {"paths": [P[0]], "rating": 5})
        listed = env.client.get("/api/mcp/actions", headers=env.login("alice")).json()["actions"]
        assert len(listed) == 1 and listed[0]["tool"] == "set_rating"
        assert env.client.get("/api/mcp/actions", headers=env.login("bob")).json()["actions"] == []
        assert env.client.get("/api/mcp/actions", headers={"Authorization": "Bearer " + alice}).status_code == 403
        db("DELETE FROM agent_actions")
        db("DELETE FROM user_preferences WHERE photo_path LIKE ?", PREFIX + "%")

    def test_rest_undo_requires_human_session_and_restores(self, world):
        env, token = world
        batch = env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})["data"]["undo"]["batch_id"]
        refused = env.client.post("/api/mcp/actions/undo", json={"batch_id": batch},
                                  headers={"Authorization": "Bearer " + token})
        assert refused.status_code == 403 and photo(P[0])[0] == 4
        human = env.login(edition=True)
        done = env.client.post("/api/mcp/actions/undo", json={"batch_id": batch}, headers=human)
        assert done.status_code == 200 and done.json()["outcomes"] == {"restored": 1} and photo(P[0])[0] == 1
        again = env.client.post("/api/mcp/actions/undo", json={"batch_id": batch}, headers=human)
        assert again.status_code == 409


class TestLimits:
    def test_batch_over_cap_still_writes_and_reports_unavailable(self, world, monkeypatch):
        env, token = world
        monkeypatch.setattr(journal, "ROWS_PER_BATCH", 2)
        result = env.call(token, "set_rating", {"paths": [P[0], P[1]], "rating": 5})
        assert result["data"]["undo"]["available"] is False and "exceed" in result["data"]["undo"]["reason"]
        assert photo(P[0])[0] == 5 and journal_rows() == []

    def test_retention_prunes_whole_batches_oldest_first(self, monkeypatch):
        monkeypatch.setattr(journal, "MAX_ROWS_PER_OWNER", 5)
        db("DELETE FROM agent_actions WHERE owner_user = ?", GAP)
        try:
            for n in range(3):
                journal.record(f"b{n}", token_id=None, source="mcp", actor=None, session_id=None, owner=GAP,
                               tool="t", rows=[(f"/k{n}/{i}", "star_rating", 0, 1) for i in range(3)])
            left = db("SELECT batch_id, COUNT(*) FROM agent_actions WHERE owner_user = ? GROUP BY batch_id "
                      "ORDER BY batch_id", GAP)
            assert left == [("b2", 3)], left
        finally:
            db("DELETE FROM agent_actions WHERE owner_user = ?", GAP)

    def test_old_batches_are_pruned_on_insert(self):
        old = (datetime.now(timezone.utc) - timedelta(days=journal.RETENTION_DAYS + 2)).isoformat(timespec="seconds")
        db("DELETE FROM agent_actions WHERE owner_user = ?", GAP)
        try:
            db("INSERT INTO agent_actions (batch_id, owner_user, tool, target_key, field, created_at) "
               "VALUES ('stale', ?, 't', '/x', 'star_rating', ?)", GAP, old)
            journal.record("fresh", token_id=None, source="mcp", actor=None, session_id=None, owner=GAP,
                           tool="t", rows=[("/y", "star_rating", 0, 1)])
            assert [r[0] for r in db("SELECT DISTINCT batch_id FROM agent_actions WHERE owner_user = ?", GAP)] == ["fresh"]
        finally:
            db("DELETE FROM agent_actions WHERE owner_user = ?", GAP)

    def test_age_prune_runs_at_startup(self, agent_app):
        old = (datetime.now(timezone.utc) - timedelta(days=journal.RETENTION_DAYS + 2)).isoformat(timespec="seconds")
        db("DELETE FROM agent_actions WHERE owner_user = ?", GAP)
        db("INSERT INTO agent_actions (batch_id, owner_user, tool, target_key, field, created_at) "
           "VALUES ('stale-startup', ?, 't', '/x', 'star_rating', ?)", GAP, old)
        db("INSERT INTO agent_actions (batch_id, owner_user, tool, target_key, field, created_at) "
           "VALUES ('fresh-startup', ?, 't', '/x', 'star_rating', ?)", GAP, datetime.now(timezone.utc).isoformat())
        try:
            agent_app("legacy")
            assert [r[0] for r in db("SELECT batch_id FROM agent_actions WHERE owner_user = ?", GAP)] == ["fresh-startup"]
        finally:
            db("DELETE FROM agent_actions WHERE owner_user = ?", GAP)

    def test_concurrent_claims_apply_once(self):
        db("DELETE FROM agent_actions WHERE owner_user = ?", GAP)
        journal.record("race", token_id=None, source="mcp", actor=None, session_id=None, owner=GAP, tool="t",
                       rows=[(f"/r/{i}", "star_rating", 0, 1) for i in range(5)])
        won, gate = [], threading.Barrier(6)

        def claim(n):
            gate.wait()
            won.append(len(journal.claim(GAP, "race", f"u{n}", ("user", "edition"))))
        try:
            threads = [threading.Thread(target=claim, args=(n,)) for n in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert sorted(won)[-1] == 5 and sum(1 for w in won if w) == 1 and len(won) == 6
        finally:
            db("DELETE FROM agent_actions WHERE owner_user = ?", GAP)


class TestStorage:
    def test_schema_columns_exist_after_init_database(self, tmp_path):
        path = str(tmp_path / "fresh.db")
        init_database(path)
        with sqlite3.connect(path) as conn:
            columns = [r[1] for r in conn.execute("PRAGMA table_info(agent_actions)")]
        assert columns == [name for name, _ in AGENT_ACTIONS_COLUMNS] and "required_level" in columns

    def test_viewer_export_has_no_agent_actions_or_tokens_table(self, tmp_path):
        from db.maintenance import export_viewer_db
        src, out = str(tmp_path / "scan.db"), str(tmp_path / "viewer.db")
        init_database(src)
        with sqlite3.connect(src) as conn:
            conn.execute("INSERT INTO agent_actions (batch_id, owner_user, tool, target_key, field, created_at) "
                         "VALUES ('b', 'o', 't', '/x', 'caption', 'now')")
            assert conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 1
        for force in (True, False):
            export_viewer_db(src, out, thumbnail_size=320, verbose=False, force=force)
            with sqlite3.connect(out) as conn:
                names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            assert "photos" in names and not names & {"agent_actions", "mcp_tokens"}, force

    def test_delete_photo_rows_keeps_the_journal(self, tmp_path):
        from db.maintenance import delete_photo_rows
        path = str(tmp_path / "keep.db")
        init_database(path)
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("INSERT INTO photos (path, filename) VALUES ('/gone.jpg', 'gone.jpg')")
            conn.execute("INSERT INTO agent_actions (batch_id, owner_user, tool, target_key, field, created_at) "
                         "VALUES ('b', 'o', 't', '/gone.jpg', 'star_rating', 'now')")
            delete_photo_rows(conn, ["/gone.jpg"])
            conn.commit()
            assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 1


class TestNotUndoable:
    def test_irreversible_tools_say_so(self, world):
        env, token = world
        cleared = env.call(token, "junk_clear", {"paths": [P[0]]})
        assert cleared["ok"] and cleared["data"].get("undoable") is False
        assert journal_rows("junk_clear") == []
