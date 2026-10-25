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


@pytest.mark.parametrize('which,payload', [
    ('keywords', '[]'), ('keywords', '{}'), ('keywords', '[null]'),
    ('keywords', '[{"Error":"cannot read file"}]'),
    ('keywords', '[{"Subject":{"bad":"shape"}}]'),
    ('keywords', '[{"Subject":[1]}]'), ('keywords', '[{"Subject":null}]'),
    ('keywords', '[{"Error":null}]'), ('keywords', 'not json'),
    ('state', '[]'), ('state', '[null]'), ('state', '{"KeywordState":null}'),
    ('state', '[{"Error":"cannot read state"}]'),
])
def test_failed_structured_reads_preserve_existing_packet_bytes(tmp_path, monkeypatch, which, payload):
    import subprocess
    from processing import xmp_export as xe
    image = tmp_path / 'photo.jpg'
    sidecar = Path(str(image) + '.xmp')
    before = build_xmp(XmpRating(tags=['foreign'])).encode()
    sidecar.write_bytes(before)
    monkeypatch.setattr(xe, '_resolve_exiftool', lambda: 'fake-exiftool')
    def run(args, **kwargs):
        assert '-overwrite_original' not in args, 'metadata write must never start after failed read'
        state = '-XMP-facet:KeywordState' in args
        raw = payload if (which == 'state') == state else '[{}]'
        return subprocess.CompletedProcess(args, 0, stdout=raw, stderr='')
    monkeypatch.setattr(xe.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='Cannot read'):
        xe._run_exiftool(str(sidecar), XmpRating(tags=['own']), timeout=1, reconcile=True)
    assert sidecar.read_bytes() == before


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
@pytest.mark.parametrize('marker', ['not json', '{"version":2}', '{"version":1,"owned":"wrong"}'])
def test_invalid_marker_is_refused_without_modifying_valid_xml(tmp_path, marker):
    from processing.xmp_export import NS_FACET
    image = tmp_path / 'photo.jpg'
    sidecar = Path(str(image) + '.xmp')
    packet = ET.fromstring(build_xmp(XmpRating(tags=['foreign'])))
    packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_FACET}}}KeywordState', marker)
    before = ET.tostring(packet)
    sidecar.write_bytes(before)
    with pytest.raises(RuntimeError, match='Unsupported or invalid'):
        write_metadata(str(image), XmpRating(tags=['own']), reconcile_keywords=True)
    assert sidecar.read_bytes() == before


def test_outbound_provenance_growth_refuses_before_writing_and_keeps_tombstones(tmp_path, monkeypatch):
    import json
    from processing import xmp_export as xe
    from processing.xmp_export import NS_FACET
    from processing.xmp_keywords import MAX_STATE_NAMES, serialize_keyword_state
    image = tmp_path / 'photo.jpg'
    sidecar = Path(str(image) + '.xmp')
    names = [f'old-{i}' for i in range(MAX_STATE_NAMES)]
    previous = {'version': 1, 'owned': names, 'deleted': [], 'ai': names, 'manual': []}
    packet = ET.fromstring(build_xmp(XmpRating()))
    packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_FACET}}}KeywordState', serialize_keyword_state(previous))
    before = ET.tostring(packet)
    sidecar.write_bytes(before)
    monkeypatch.setattr(xe, '_resolve_exiftool', lambda: 'fake-exiftool')
    def run(args, **kwargs):
        import subprocess
        assert '-overwrite_original' not in args
        record = {'KeywordState': json.dumps(previous)} if '-XMP-facet:KeywordState' in args else {'Subject': names}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps([record]), stderr='')
    monkeypatch.setattr(xe.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='safe packet bounds.*Deletion markers were not discarded'):
        xe._run_exiftool(str(sidecar), XmpRating(tags=['new-ai'], ai_tags=['new-ai']), timeout=1, reconcile=True)
    assert sidecar.read_bytes() == before


@pytest.mark.parametrize('tags', [['x' * 1025], [f'tag{i}' for i in range(10001)]])
def test_unrepresentable_new_keyword_state_never_creates_fallback_packet(tmp_path, monkeypatch, tags):
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    image = tmp_path / 'photo.jpg'
    with pytest.raises(RuntimeError, match='safe packet bounds'):
        write_metadata(str(image), XmpRating(tags=tags))
    assert not Path(str(image) + '.xmp').exists()


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_embedded_marker_and_unicode_case_normalization_preserve_foreign_collision(tmp_path):
    import subprocess
    from PIL import Image
    from processing import xmp_export as xe
    image = tmp_path / 'photo.jpg'
    Image.new('RGB', (20, 20), 'blue').save(image)
    subprocess.run(['exiftool', '-overwrite_original', '-XMP-dc:Subject=CAFÉ', str(image)],
                   check=True, capture_output=True)
    write_metadata(str(image), XmpRating(tags=['Cafe\u0301', 'Straße'], manual_tags=['Straße']), embed_original=True)
    state = xe._read_keyword_state(str(image), xe._resolve_exiftool(), timeout=30)
    assert state['owned'] == ['Straße']  # NFC/case-equal foreign CAFÉ is never claimed.
    subprocess.run(['exiftool', '-overwrite_original', '-XMP-dc:Subject=CAFÉ', '-XMP-dc:Subject=STRASSE', str(image)],
                   check=True, capture_output=True)
    write_metadata(str(image), XmpRating(), embed_original=True, reconcile_keywords=True)
    flat, _ = xe._read_existing_keywords(str(image), xe._resolve_exiftool(), timeout=30, strict=True)
    assert flat == ['CAFÉ']
    state = xe._read_keyword_state(str(image), xe._resolve_exiftool(), timeout=30)
    assert state['deleted'] == ['Straße']


def test_explicit_null_marker_is_invalid_before_any_write(tmp_path, monkeypatch):
    import subprocess
    from processing import xmp_export as xe
    image = tmp_path / 'photo.jpg'
    sidecar = Path(str(image) + '.xmp')
    before = build_xmp(XmpRating(tags=['foreign'])).encode()
    sidecar.write_bytes(before)
    monkeypatch.setattr(xe, '_resolve_exiftool', lambda: 'fake-exiftool')
    def run(args, **kwargs):
        assert '-overwrite_original' not in args
        payload = '[{"KeywordState":null}]' if '-XMP-facet:KeywordState' in args else '[{}]'
        return subprocess.CompletedProcess(args, 0, stdout=payload, stderr='')
    monkeypatch.setattr(xe.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='Unsupported or invalid'):
        xe._run_exiftool(str(sidecar), XmpRating(), timeout=1, reconcile=True)
    assert sidecar.read_bytes() == before


def test_foreign_case_and_normalization_display_variants_are_not_collapsed():
    foreign = ['CAFÉ', 'Cafe\u0301', 'café']
    flat, state = reconcile_keywords(foreign, ['café'])
    assert flat == foreign
    assert state['owned'] == []
    flat, state = reconcile_keywords(flat, [], state, reconcile=True)
    assert flat == foreign
