"""Face export must not adopt another editor's rectangles by name or position."""
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET
from types import SimpleNamespace

import pytest
from PIL import Image

from processing import xmp_export as xe


EXE = xe._resolve_exiftool()
CONFIG = str(Path(xe.__file__).with_name("facet_exiftool.config"))
FOREIGN = {"Name": "Same name", "Type": "Face",
           "Area": {"X": 0.2, "Y": 0.3, "W": 0.1, "H": 0.2, "Unit": "normalized"},
           "Description": "External editor, untouched",
           "Extensions": {"XMP-dc:Creator": ["Other editor"]}}


def _info(regions, width=100):
    return {"AppliedToDimensions": {"W": width, "H": 80, "Unit": "pixel"},
            "RegionList": regions}


def _face(name="Same name"):
    return xe.FaceRegion.from_bbox(name, 30, 20, 60, 50, 100, 80)


def test_unmarked_regions_are_not_rewritten_even_with_same_name():
    args = xe._region_args([_face()], _info([FOREIGN]))
    assert not any("RegionInfo=" in arg or "RegionList-=" in arg for arg in args)
    assert json.loads(next(arg for arg in args if arg.startswith("-XMP-mwg-rs:RegionList+=")).split("=", 1)[1])["Name"] == FOREIGN["Name"]


def test_only_explicitly_owned_regions_are_cleared():
    owned = json.loads(next(arg for arg in xe._region_args([_face()]) if arg.startswith("-XMP-mwg-rs:RegionList+=")).split("=", 1)[1])
    args = xe._region_args([], _info([FOREIGN, owned]))
    assert len(args) == 3
    deletion = next(arg for arg in args if arg.startswith("-XMP-mwg-rs:RegionList-="))
    assert json.loads(deletion.split("=", 1)[1]) == owned
    assert xe._region_args([], _info([FOREIGN])) == []


def test_foreign_dimensions_are_not_silently_reinterpreted(caplog):
    assert xe._region_args([_face()], _info([FOREIGN], width=200)) == []
    assert "Skipping face regions" in caplog.text


@pytest.mark.skipif(not EXE, reason="ExifTool not installed")
@pytest.mark.parametrize("embedded", [False, True])
def test_real_writer_preserves_foreign_regions_on_update_and_clear(tmp_path, embedded):
    image = tmp_path / "portrait.jpg"
    Image.new("RGB", (100, 80), "blue").save(image)
    original = image.read_bytes()
    target = image if embedded else tmp_path / "portrait.jpg.xmp"
    subprocess.run([EXE, "-config", CONFIG, "-api", "StructFormat=JSON",
                    "-XMP-mwg-rs:RegionInfo=" + json.dumps(_info([FOREIGN])),
                    "-overwrite_original", str(target)], check=True, capture_output=True)

    def read():
        return xe._read_existing_regions(str(target), EXE, timeout=30)

    expected_foreign = read()["RegionList"][0]
    # Delimiters and non-ASCII names must be data, not serialized structure syntax.
    name = "Renée, {日}|[name]"
    rating = xe.XmpRating(regions=[_face(name)])
    xe.write_metadata(str(image), rating, embed_original=embedded)
    after = read()["RegionList"]
    assert after[0] == expected_foreign
    assert after[1]["Name"] == name
    assert after[1]["Extensions"] == {"XMP-facet:RegionOwner": "Facet"}
    xe.write_metadata(str(image), rating, embed_original=embedded)
    assert read()["RegionList"] == after  # idempotent, no duplicate owned boxes
    xe.write_metadata(str(image), xe.XmpRating(), embed_original=embedded)
    assert read()["RegionList"] == [expected_foreign]
    if not embedded:
        assert image.read_bytes() == original


@pytest.mark.skipif(not EXE, reason="ExifTool not installed")
def test_clear_last_owned_region_really_removes_the_list(tmp_path):
    image = tmp_path / "portrait.jpg"
    Image.new("RGB", (100, 80), "blue").save(image)
    xe.write_metadata(str(image), xe.XmpRating(regions=[_face()]))
    xe.write_metadata(str(image), xe.XmpRating())
    info = xe._read_existing_regions(str(image) + ".xmp", EXE, timeout=30)
    assert not info.get("RegionList")


@pytest.mark.skipif(not EXE, reason="ExifTool not installed")
def test_unreadable_existing_metadata_refuses_write(tmp_path):
    target = tmp_path / "portrait.jpg.xmp"
    target.write_bytes(b"not valid XMP")
    with pytest.raises(RuntimeError, match="Cannot read face metadata"):
        xe._run_exiftool(str(target), xe.XmpRating(regions=[_face()]), timeout=30)
    assert target.read_bytes() == b"not valid XMP"


@pytest.mark.skipif(not EXE, reason="ExifTool not installed")
def test_unknown_foreign_extension_survives_owned_face_updates(tmp_path):
    from xml.etree import ElementTree as ET
    image = tmp_path / "portrait.jpg"
    Image.new("RGB", (100, 80), "blue").save(image)
    target = tmp_path / "portrait.jpg.xmp"
    subprocess.run([EXE, "-api", "StructFormat=JSON",
                    "-XMP-mwg-rs:RegionInfo=" + json.dumps(_info([FOREIGN])),
                    str(target)], check=True, capture_output=True)
    ns = {"m": "http://www.metadataworkinggroup.com/schemas/regions/", "r": xe.NS_RDF}
    tree = ET.parse(target)
    region = tree.find(".//m:RegionList/r:Bag/r:li", ns)
    extensions = region.find("m:Extensions", ns)
    ET.SubElement(extensions, "{urn:another-editor:private}OriginalIdentity").text = "foreign-123"
    tree.write(target, encoding="utf-8")
    for rating in (xe.XmpRating(regions=[_face()]), xe.XmpRating()):
        xe.write_metadata(str(image), rating)
        saved = ET.parse(target).find(".//{urn:another-editor:private}OriginalIdentity")
        assert saved is not None and saved.text == "foreign-123"


@pytest.mark.skipif(not EXE, reason="ExifTool not installed")
@pytest.mark.parametrize("name", ["1.50", "1e3", "true", "false", "null"])
@pytest.mark.parametrize("embedded", [False, True])
def test_numeric_names_and_formatted_areas_repeat_drift_and_clear(tmp_path, name, embedded):
    image = tmp_path / "numeric.jpg"
    Image.new("RGB", (100, 80), "blue").save(image)
    target = image if embedded else Path(str(image) + ".xmp")
    rating = xe.XmpRating(regions=[_face(name)])
    xe._run_exiftool(str(target), rating, timeout=30)
    raw = subprocess.check_output([EXE, "-b", "-XMP", str(target)])
    tree = ET.fromstring(raw)
    tree.find(".//{http://ns.adobe.com/xmp/sType/Area#}x").text = "0.450000"
    packet = ET.tostring(tree)
    if embedded:
        source = tmp_path / "formatted.xmp"
        source.write_bytes(packet)
        subprocess.run([EXE, "-XMP<=" + str(source), "-overwrite_original", str(target)], check=True, capture_output=True)
    else:
        target.write_bytes(packet)
    for _ in range(2):
        xe._run_exiftool(str(target), rating, timeout=30)
        regions = xe._read_existing_regions(str(target), EXE, timeout=30)["RegionList"]
        assert len(regions) == 1
        assert regions[0]["Name"] == name
    drift = xe.XmpRating(regions=[xe.FaceRegion.from_bbox(name, 10, 10, 40, 40, 100, 80)])
    xe._run_exiftool(str(target), drift, timeout=30)
    regions = xe._read_existing_regions(str(target), EXE, timeout=30)["RegionList"]
    assert len(regions) == 1 and float(regions[0]["Area"]["X"]) == .25
    xe._run_exiftool(str(target), xe.XmpRating(), timeout=30)
    assert not xe._read_existing_regions(str(target), EXE, timeout=30).get("RegionList")


@pytest.mark.skipif(not EXE, reason="ExifTool not installed")
@pytest.mark.parametrize("conflict", ["mixed", "foreign_missing", "foreign_mismatch"])
def test_dimension_conflicts_skip_faces_but_write_other_metadata(tmp_path, caplog, conflict):
    image = tmp_path / "dimensions.jpg"
    Image.new("RGB", (100, 80), "blue").save(image)
    target = Path(str(image) + ".xmp")
    info = _info([FOREIGN], width=200 if conflict == "foreign_mismatch" else 100)
    if conflict == "foreign_missing":
        del info["AppliedToDimensions"]
    subprocess.run([EXE, "-config", CONFIG, "-api", "StructFormat=JSON",
                    "-XMP-mwg-rs:RegionInfo=" + json.dumps(info), str(target)], check=True, capture_output=True)
    before = xe._read_existing_regions(str(target), EXE, timeout=30)
    faces = [_face()]
    if conflict == "mixed":
        faces.append(xe.FaceRegion.from_bbox("manual preview", 5, 5, 10, 10, 640, 480))
    rating = xe.XmpRating(star_rating=4, is_favorite=True, tags=["own-tag"], regions=faces,
                          gps_manually_set=True, gps_latitude=10, gps_longitude=20)
    xe.write_metadata(str(image), rating)
    from processing.xmp_import import parse_sidecar
    parsed = parse_sidecar(str(target))
    assert parsed["star_rating"] == 4 and parsed["is_favorite"]
    assert "own-tag" in parsed["tags"] and parsed["gps"] == (10, 20)
    assert xe._read_existing_regions(str(target), EXE, timeout=30) == before
    assert "Skipping face regions" in caplog.text


@pytest.mark.parametrize("response", [[], [None], [{"Error": "bad metadata"}], [{"RegionInfo": []}],
                                       [{"RegionInfo": {"RegionList": "invalid"}}],
                                       [{"RegionInfo": {"RegionList": [None]}}]])
def test_invalid_region_read_fails_closed_without_writing(tmp_path, monkeypatch, response):
    target = tmp_path / "valid.xmp"
    target.write_text(xe.build_xmp(xe.XmpRating()), encoding="utf-8")
    before = target.read_bytes()
    monkeypatch.setattr(xe.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(response)))
    with pytest.raises(xe.MetadataPreconditionError):
        info = xe._read_existing_regions(str(target), "exiftool", timeout=1)
        xe._region_args([_face()], info)
    assert target.read_bytes() == before


@pytest.mark.parametrize("failure", [OSError("read failed"), subprocess.TimeoutExpired("exiftool", 1)])
def test_region_reader_timeout_or_io_failure_is_a_precondition(tmp_path, monkeypatch, failure):
    target = tmp_path / "valid.xmp"
    target.write_text(xe.build_xmp(xe.XmpRating()), encoding="utf-8")
    before = target.read_bytes()
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(xe.subprocess, "run", fail)
    with pytest.raises(xe.MetadataPreconditionError):
        xe._read_existing_regions(str(target), "exiftool", timeout=1)
    assert target.read_bytes() == before


@pytest.mark.skipif(not EXE, reason="ExifTool not installed")
def test_legacy_unmarked_matching_region_is_not_adopted(tmp_path):
    image = tmp_path / "legacy.jpg"
    Image.new("RGB", (100, 80), "blue").save(image)
    target = Path(str(image) + ".xmp")
    legacy = json.loads(next(arg for arg in xe._region_args([_face("Alice")])
                             if arg.startswith("-XMP-mwg-rs:RegionList+=")).split("=", 1)[1])
    del legacy["Extensions"]
    subprocess.run([EXE, "-api", "StructFormat=JSON", "-XMP-mwg-rs:RegionInfo=" + json.dumps(_info([legacy])),
                    str(target)], check=True, capture_output=True)
    xe.write_metadata(str(image), xe.XmpRating(regions=[_face("Alice")]))
    regions = xe._read_existing_regions(str(target), EXE, timeout=30)["RegionList"]
    assert len(regions) == 2
    assert sum(xe._region_is_owned(region) for region in regions) == 1
    xe.write_metadata(str(image), xe.XmpRating())
    regions = xe._read_existing_regions(str(target), EXE, timeout=30)["RegionList"]
    assert len(regions) == 1 and not xe._region_is_owned(regions[0])


@pytest.mark.parametrize("returncode,stdout", [(1, "[]"), (0, "not JSON")])
def test_region_reader_rejects_failed_or_unparseable_response(tmp_path, monkeypatch, returncode, stdout):
    target = tmp_path / "valid.xmp"
    target.write_text(xe.build_xmp(xe.XmpRating()), encoding="utf-8")
    before = target.read_bytes()
    monkeypatch.setattr(xe.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=returncode, stdout=stdout))
    with pytest.raises(xe.MetadataPreconditionError):
        xe._read_existing_regions(str(target), "exiftool", timeout=1)
    assert target.read_bytes() == before
