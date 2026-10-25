"""Real packet/DB coverage for explicit flat-keyword reconciliation."""
import sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from db.manual_tags import delete_manual_tag, insert_manual_tag, load_manual_tags
from db.schema import init_database
from processing.xmp_export import NS_DC, NS_RDF, XmpRating, build_xmp, export_sidecars, exiftool_available, write_metadata
from processing.xmp_import import import_sidecars, parse_sidecar
from processing.xmp_keywords import reconcile_keywords


def database(tmp_path):
    path = tmp_path / 'test.db'
    init_database(str(path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def packet_keywords(sidecar):
    return parse_sidecar(str(sidecar))['tags']


def add_external_keyword(sidecar, keyword):
    packet = ET.parse(sidecar)
    bag = packet.find(f'.//{{{NS_DC}}}subject/{{{NS_RDF}}}Bag')
    ET.SubElement(bag, f'{{{NS_RDF}}}li').text = keyword
    packet.write(sidecar, encoding='utf-8', xml_declaration=True)


def test_foreign_name_collision_is_never_claimed_and_readd_remains_owned():
    flat, state = reconcile_keywords(['Foreign', 'same'], ['same', 'owned'], ai=['owned'])
    assert state['owned'] == ['owned']
    assert state['ai'] == ['owned']
    flat, state = reconcile_keywords(flat, [], state, reconcile=True)
    assert flat == ['Foreign', 'same']
    assert state['deleted'] == ['owned']
    flat, state = reconcile_keywords([*flat, 'owned'], ['owned'], state, reconcile=True)
    assert state['owned'] == ['owned']
    assert state['deleted'] == []
    flat, state = reconcile_keywords(flat, [], state, reconcile=True)
    assert flat == ['Foreign', 'same']


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_deleted_manual_keyword_cannot_return_and_foreign_nodes_survive(tmp_path):
    from PIL import Image
    image = tmp_path / 'photo.jpg'
    Image.new('RGB', (20, 20), 'blue').save(image)
    original = image.read_bytes()
    sidecar = Path(str(image) + '.xmp')
    sidecar.write_text(build_xmp(XmpRating(tags=['foreign'])))
    # Simulate an older external packet with no Facet ownership.
    packet = ET.parse(sidecar)
    for node in packet.iter():
        for key in list(node.attrib):
            if key.endswith('KeywordState'):
                del node.attrib[key]
    packet.write(sidecar, encoding='utf-8')
    conn = database(tmp_path)
    try:
        conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'machine'))
        insert_manual_tag(conn, str(image), 'delete-me')
        conn.commit()
        assert export_sidecars(conn)['written'] == 1
        assert set(packet_keywords(sidecar)) == {'foreign', 'machine', 'delete-me'}
        delete_manual_tag(conn, str(image), 'delete-me')
        conn.commit()
        # Additive default explicitly retains old keywords until reconciliation.
        export_sidecars(conn)
        assert 'delete-me' in packet_keywords(sidecar)
        export_sidecars(conn, reconcile_keywords=True)
        assert set(packet_keywords(sidecar)) == {'foreign', 'machine'}
        assert 'delete-me' in parse_sidecar(str(sidecar))['keyword_state']['deleted']
        # External editors often preserve private markers while copying subjects.
        add_external_keyword(sidecar, 'DELETE-ME')
        import_sidecars(conn)
        assert load_manual_tags(conn, str(image)) == ['foreign']
        export_sidecars(conn, reconcile_keywords=True)
        assert set(packet_keywords(sidecar)) == {'foreign', 'machine'}
        assert image.read_bytes() == original
    finally:
        conn.close()


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_retag_does_not_turn_previous_ai_into_manual_and_manual_duplicate_restores(tmp_path):
    from PIL import Image
    image = tmp_path / 'photo.jpg'
    Image.new('RGB', (10, 10)).save(image)
    sidecar = Path(str(image) + '.xmp')
    conn = database(tmp_path)
    try:
        conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'old-ai, shared'))
        insert_manual_tag(conn, str(image), 'shared')
        insert_manual_tag(conn, str(image), 'manual')
        conn.commit()
        export_sidecars(conn)
        conn.execute('UPDATE photos SET tags=?', ('new-ai',))
        conn.commit()
        # An old exported AI label must not become a permanent manual label.
        import_sidecars(conn)
        assert load_manual_tags(conn, str(image)) == ['manual', 'shared']
        export_sidecars(conn, reconcile_keywords=True)
        assert set(packet_keywords(sidecar)) == {'new-ai', 'manual', 'shared'}
        conn.execute('DELETE FROM photo_manual_tags')
        conn.commit()
        import_sidecars(conn)
        assert load_manual_tags(conn, str(image)) == ['manual', 'shared']
    finally:
        conn.close()


def test_fallback_tracks_ai_and_manual_provenance_without_exiftool(tmp_path, monkeypatch):
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    image = tmp_path / 'photo.jpg'
    image.write_bytes(b'original')
    rating = XmpRating(tags=['ai', 'manual'], ai_tags=['ai'], manual_tags=['manual'])
    write_metadata(str(image), rating)
    conn = database(tmp_path)
    try:
        conn.execute('INSERT INTO photos(path) VALUES (?)', (str(image),))
        conn.commit()
        import_sidecars(conn)
        assert load_manual_tags(conn, str(image)) == ['manual']
        before = Path(str(image) + '.xmp').read_bytes()
        with pytest.raises(RuntimeError, match='requires ExifTool'):
            write_metadata(str(image), XmpRating(), reconcile_keywords=True)
        assert Path(str(image) + '.xmp').read_bytes() == before
    finally:
        conn.close()


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_keyword_reconciliation_respects_user_visibility(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: True)
    visible = tmp_path / 'alice.jpg'
    hidden = tmp_path / 'bob.jpg'
    monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda user: ('photos.path = ?', [str(visible)]))
    conn = database(tmp_path)
    try:
        for image in (visible, hidden):
            Image.new('RGB', (10, 10)).save(image)
            conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'old'))
        conn.commit()
        export_sidecars(conn)
        hidden_packet = Path(str(hidden) + '.xmp').read_bytes()
        conn.execute('UPDATE photos SET tags=?', ('new',))
        conn.commit()
        assert export_sidecars(conn, user_id='alice', reconcile_keywords=True)['written'] == 1
        assert packet_keywords(Path(str(visible) + '.xmp')) == ['new']
        assert Path(str(hidden) + '.xmp').read_bytes() == hidden_packet
        import_sidecars(conn, user_id='alice')
        assert load_manual_tags(conn, str(hidden)) == []
    finally:
        conn.close()
