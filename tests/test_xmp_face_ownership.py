"""Face export must not adopt another editor's rectangles by name or position."""
import json
import subprocess
from pathlib import Path

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
    assert json.loads(args[-1].split("=", 1)[1])["Name"] == FOREIGN["Name"]


def test_only_explicitly_owned_regions_are_cleared():
    owned = json.loads(xe._region_args([_face()])[-1].split("=", 1)[1])
    args = xe._region_args([], _info([FOREIGN, owned]))
    assert len(args) == 3
    assert args[-1].startswith("-XMP-mwg-rs:RegionList-=")
    assert json.loads(args[-1].split("=", 1)[1]) == owned
    assert xe._region_args([], _info([FOREIGN])) == []


def test_foreign_dimensions_are_not_silently_reinterpreted():
    with pytest.raises(RuntimeError, match="different or unknown"):
        xe._region_args([_face()], _info([FOREIGN], width=200))


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
    with pytest.raises(RuntimeError, match="cannot read face metadata"):
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
