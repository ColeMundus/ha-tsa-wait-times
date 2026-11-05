"""Packaging exercises real files and substantive rejection paths."""

import json
import re
import shutil
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from PIL import Image

from scripts.package import REQUIRED, build


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "source"
    original = Path(__file__).resolve().parents[1]
    for name in REQUIRED:
        dest = root / "custom_components/tsa_wait_times" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original / "custom_components/tsa_wait_times" / name, dest)
    shutil.copyfile(original / "LICENSE", root / "LICENSE")
    return root


def test_package(tree, tmp_path):
    archive = build(tree, tmp_path / "out")
    first = archive.read_bytes()
    assert build(tree, tmp_path / "out").read_bytes() == first
    with zipfile.ZipFile(archive) as bundle:
        assert len(bundle.namelist()) == len(REQUIRED) + 1
        assert "LICENSE" in bundle.namelist()
        icon_path = "custom_components/tsa_wait_times/brand/icon.png"
        with Image.open(BytesIO(bundle.read(icon_path))) as icon:
            assert icon.format == "PNG"
            assert icon.size == (256, 256)
            icon.verify()
        assert bundle.read(icon_path) == (tree / icon_path).read_bytes()
        assert "https://www.tsa.gov/" in bundle.read("LICENSE").decode()
        assert bundle.testzip() is None
    assert archive.with_suffix(".zip.sha256").exists()


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "symlink",
        "version",
        "syntax",
        "icon_missing",
        "icon_invalid",
        "icon_size",
    ],
)
def test_reject(tree, tmp_path, damage):
    component = tree / "custom_components/tsa_wait_times"
    if damage == "missing":
        (tree / "LICENSE").unlink()
    elif damage == "symlink":
        (component / "client.py").unlink()
        (component / "client.py").symlink_to(tree / "LICENSE")
    elif damage == "version":
        manifest = json.loads((component / "manifest.json").read_text())
        manifest["version"] = "../../unsafe"
        (component / "manifest.json").write_text(json.dumps(manifest))
    elif damage == "icon_missing":
        (component / "brand/icon.png").unlink()
    elif damage == "icon_invalid":
        (component / "brand/icon.png").write_bytes(b"not an image")
    elif damage == "icon_size":
        Image.new("RGBA", (128, 128)).save(component / "brand/icon.png")
    else:
        (component / "client.py").write_text("def broken(:")
    with pytest.raises((ValueError, SyntaxError)):
        build(tree, tmp_path / "out")


def test_readme_branding():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text()
    sources = []

    class Images(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "img":
                sources.append(dict(attrs)["src"])

    Images().feed(readme)
    assert sources
    for source in sources:
        parsed = urlsplit(source)
        assert parsed.scheme == "https" and parsed.netloc
    assert sources == [
        "https://raw.githubusercontent.com/ColeMundus/ha-tsa-wait-times/"
        "main/custom_components/tsa_wait_times/brand/icon.png"
    ]
    badges = re.findall(r"\[!\[([^\]]+)\]\(([^)]+)\)\]\(([^)]+)\)", readme)
    assert len(badges) == 4
    assert all(urlsplit(image).scheme == "https" for _, image, _ in badges)
    assert any(
        label == "CI workflow" and target.endswith("/ci.yml")
        for label, _, target in badges
    )
    assert any(
        label == "Code license MIT" and target == "LICENSE"
        for label, _, target in badges
    )
    assert any("not listed" in label for label, _, _ in badges)
