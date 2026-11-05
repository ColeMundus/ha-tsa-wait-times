"""Packaging exercises real files and substantive rejection paths."""

import json
import shutil
import zipfile
from pathlib import Path

import pytest

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
        assert bundle.testzip() is None
    assert archive.with_suffix(".zip.sha256").exists()


@pytest.mark.parametrize("damage", ["missing", "symlink", "version", "syntax"])
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
    else:
        (component / "client.py").write_text("def broken(:")
    with pytest.raises((ValueError, SyntaxError)):
        build(tree, tmp_path / "out")
