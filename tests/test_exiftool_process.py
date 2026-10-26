"""Exercise the real Unicode transport under simulated Windows ANSI boundaries."""
import json
import shutil
import subprocess
import os
import stat
from pathlib import Path

import pytest
from PIL import Image

from utils.exiftool_process import run_exiftool_process


def test_ascii_arguments_keep_direct_argv_and_decode_output_as_utf8(monkeypatch):
    seen = []
    arguments = ['exiftool', '-XMP-dc:Description= # literal\n-overwrite_original', '/tmp/ascii.jpg']
    monkeypatch.setattr(subprocess, 'run', lambda args, **kwargs: seen.append((args, kwargs)))
    run_exiftool_process(arguments, timeout=3)
    assert seen[0][0] == arguments
    assert seen[0][1]['encoding'] == 'utf-8'
    assert 'input' not in seen[0][1]


@pytest.mark.parametrize('operator', ['=', '+=', '-='])
def test_utf8_argfile_preserves_values_operators_and_keeps_config_first(monkeypatch, operator):
    seen = []
    value = '# 日本\r\n-overwrite_original\nline \\n $ @'
    def run(args, **kwargs):
        lines = kwargs['input'].splitlines()
        prefix = '-XMP-dc:Description' + operator[:-1] + '<='
        assert lines[0].startswith(prefix)
        filename = Path(lines[0][len(prefix):])
        assert filename.read_bytes() == value.encode('utf-8')
        if os.name != 'nt':
            assert stat.S_IMODE(filename.stat().st_mode) == 0o600
            assert stat.S_IMODE(filename.parent.stat().st_mode) == 0o700
        seen.append((args, kwargs, filename))
    monkeypatch.setattr(subprocess, 'run', run)
    run_exiftool_process(['exiftool', '-config', 'facet.config', '-XMP-dc:Description' + operator + value,
                          'Renée.jpg'], timeout=3)
    command, options, filename = seen[0]
    assert command == ['exiftool', '-config', 'facet.config', '-charset', 'filename=UTF8',
                       '-charset', 'UTF8', '-@', '-']
    assert options['encoding'] == 'utf-8'
    assert options['input'].splitlines()[1:] == ['Renée.jpg']
    assert not filename.exists()


def test_plain_unicode_values_preserve_leading_space_hash_and_backslashes(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, 'run', lambda args, **kwargs: seen.append(kwargs['input']))
    run_exiftool_process(['exiftool', '-XMP-dc:Description= # 日本 \\n $ @  ', '/tmp/# 日本.jpg'], timeout=1)
    assert seen == ['-XMP-dc:Description=  # 日本 \\n $ @  \n/tmp/# 日本.jpg\n']


def test_newline_filename_is_a_catchable_runtime_failure_before_process_start(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail('must refuse before process start'))
    with pytest.raises(RuntimeError, match='filename or option contains a newline'):
        run_exiftool_process(['exiftool', '-XMP-dc:Subject=café', '/tmp/a\nb.jpg'], timeout=1)


def test_newline_file_include_assignment_is_refused_before_process_start(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail('must refuse before process start'))
    with pytest.raises(RuntimeError, match='filename or option contains a newline'):
        run_exiftool_process(['exiftool', '-XMP-dc:Subject=café', '-Tag<=a\nb', '/tmp/a.jpg'], timeout=1)


@pytest.mark.skipif(os.name == 'nt' or shutil.which('exiftool') is None,
                    reason='requires ExifTool and a filesystem allowing newline filenames')
def test_one_newline_filename_does_not_abort_other_photo_exports(tmp_path):
    import sqlite3
    from db.schema import init_database
    from processing import xmp_export as xe
    db = tmp_path / 'test.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        for name in ('safe.jpg', 'a\nb.jpg', 'also-safe.jpg'):
            image = tmp_path / name
            Image.new('RGB', (16, 16), 'blue').save(image)
            conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'café'))
        conn.commit()
        result = xe.export_sidecars(conn)
    assert result['written'] == 2 and result['errors'] == 1
    assert (tmp_path / 'safe.jpg.xmp').exists()
    assert (tmp_path / 'also-safe.jpg.xmp').exists()


@pytest.mark.skipif(shutil.which('exiftool') is None, reason='requires ExifTool')
@pytest.mark.parametrize('embedded', [False, True])
@pytest.mark.parametrize('caption', ['# Renée 日本\r\n-overwrite_original\nsecond line \\n literal \\path "quote" $ @  ',
                                    '  # Renée 日本 \\n literal \\path "quote" $ @  '])
def test_real_writer_preserves_unicode_under_windows_ansi_transport(tmp_path, monkeypatch, embedded, caption):
    from processing import xmp_export as xe
    original_run = subprocess.run
    def windows_ansi_run(args, **kwargs):
        # Reproduce both Windows narrow argv loss and Python's cp1252 default.
        args = [value.encode('cp1252', errors='replace').decode('cp1252') for value in args]
        if kwargs.get('text') and 'encoding' not in kwargs:
            kwargs['encoding'] = 'cp1252'
        return original_run(args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', windows_ansi_run)
    image = tmp_path / '日本 Renée.jpg'
    Image.new('RGB', (100, 80), 'blue').save(image)
    before = image.read_bytes()
    name = 'Renée, {日}|[name]'
    rating = xe.XmpRating(tags=['café', 'Straße'], caption=caption,
                         regions=[xe.FaceRegion.from_bbox(name, 30, 20, 60, 50, 100, 80)])
    xe.write_metadata(str(image), rating, embed_original=embedded)
    targets = [Path(str(image) + '.xmp')] + ([image] if embedded else [])
    for target in targets:
        result = run_exiftool_process([xe._resolve_exiftool(), '-json', '-struct', '-XMP-dc:Subject',
                                      '-XMP-dc:Description', '-XMP-mwg-rs:RegionInfo', str(target)], timeout=30)
        assert result.returncode == 0, result.stderr
        record = json.loads(result.stdout)[0]
        assert record['Subject'] == ['café', 'Straße']
        assert record['Description'] == caption
        assert record['RegionInfo']['RegionList'][0]['Name'] == name
        # Literal spaces in foreign keywords also survive the ordinary argfile
        # parser; Facet's separate typed-tag normalization is not involved here.
        result = run_exiftool_process([xe._resolve_exiftool(), '-overwrite_original',
                                      '-XMP-dc:Subject= # café  ', str(target)], timeout=30)
        assert result.returncode == 0, result.stderr
        result = run_exiftool_process([xe._resolve_exiftool(), '-json', '-XMP-dc:Subject', str(target)], timeout=30)
        assert json.loads(result.stdout)[0]['Subject'] == ' # café  '
    if not embedded:
        assert image.read_bytes() == before
