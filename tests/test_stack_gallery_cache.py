"""A stack owner's gallery pages reuse the count caches and still see stack edits."""
import pytest

from api import db_helpers

PREFIX = '/stack-gallery-cache/'
PARAMS = {'path_prefix': PREFIX, 'hide_bursts': '1'}


@pytest.fixture
def stack(edition_client, seed_photos_prefix):
    rows = [{'path': PREFIX + f'p{i}.jpg', 'filename': f'p{i}.jpg', 'aggregate': 8.0 - i,
             'is_burst_lead': int(i == 0), 'burst_group_id': 654} for i in range(3)]
    rows.append({'path': PREFIX + 'single.jpg', 'filename': 'single.jpg', 'aggregate': 4.0})
    seed_photos_prefix(PREFIX, rows)
    r = edition_client.post('/api/stacks', json={
        'paths': [PREFIX + 'p0.jpg', PREFIX + 'p1.jpg'], 'cover_path': PREFIX + 'p0.jpg'})
    assert r.status_code == 201, r.text
    return r.json()['stack']


def page(client):
    r = client.get('/api/photos', params=PARAMS)
    assert r.status_code == 200, r.text
    return r.json()


def test_stack_owner_pages_are_served_from_the_count_caches(edition_client, stack, monkeypatch):
    lookups = []
    original = db_helpers._count_cache_lookup

    def spy(key):
        value = original(key)
        lookups.append((key.startswith('hs:'), value is not None))
        return value

    monkeypatch.setattr(db_helpers, '_count_cache_lookup', spy)
    first = page(edition_client)
    lookups.clear()
    second = page(edition_client)
    assert (second['total'], second['photo_total'], second['hidden_summary']) == (
        first['total'], first['photo_total'], first['hidden_summary'])
    assert (False, True) in lookups  # COUNT
    assert (True, True) in lookups  # hidden summary


def test_a_stack_edit_is_visible_on_the_next_page_despite_the_cache(edition_client, stack):
    before = page(edition_client)
    r = edition_client.delete(f"/api/stacks/{stack['id']}", params={'expected_revision': stack['revision']})
    assert r.status_code == 200, r.text
    after = page(edition_client)
    # The burst follower p1 was restored by its stack; unstacked, the burst hide takes it again.
    assert before['photo_total'] == 3
    assert after['photo_total'] == 2
    assert after['hidden_summary']['bursts'] == before['hidden_summary']['bursts'] + 1
