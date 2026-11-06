"""Build a validated manual-install ZIP (not a HACS release asset)."""

import argparse
import ast
import hashlib
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

REQUIRED = {
    "__init__.py",
    "airports.py",
    "binary_sensor.py",
    "brand/icon.png",
    "client.py",
    "config_flow.py",
    "const.py",
    "diagnostics.py",
    "entity.py",
    "sensor.py",
    "manifest.json",
    "strings.json",
    "translations/en.json",
}


def build(root: Path, output: Path) -> Path:
    """Allowlist runtime files; reject unsafe paths and missing required content."""
    component = root / "custom_components" / "tsa_wait_times"
    paths = [
        (component / name, f"custom_components/tsa_wait_times/{name}")
        for name in sorted(REQUIRED)
    ]
    paths += [(root / "LICENSE", "LICENSE")]
    contents = {}
    for source, target in paths:
        if (
            source.is_symlink()
            or not source.is_file()
            or not source.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError(f"Missing or unsafe package input: {target}")
        raw = source.read_bytes()
        if source.suffix == ".py":
            ast.parse(raw, filename=target)
        elif source.suffix == ".json":
            json.loads(raw)
        elif source.suffix == ".png":
            try:
                with Image.open(BytesIO(raw)) as image:
                    if image.format != "PNG" or image.size != (256, 256):
                        raise ValueError("Brand icon must be a 256x256 PNG")
                    image.verify()
            except OSError as err:
                raise ValueError("Invalid brand icon") from err
        contents[target] = raw
    manifest = json.loads(contents["custom_components/tsa_wait_times/manifest.json"])
    version = manifest["version"]
    if not isinstance(version, str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:b[0-9]+)?", version
    ):
        raise ValueError("Unsafe version")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"tsa-wait-times-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for target, raw in sorted(contents.items()):
            info = zipfile.ZipInfo(target, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, raw)
    with zipfile.ZipFile(archive) as bundle:
        if set(bundle.namelist()) != set(contents) or bundle.testzip() is not None:
            raise ValueError("Archive validation failed")
        for target, raw in contents.items():
            if bundle.read(target) != raw:
                raise ValueError("Archive content mismatch")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n")
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    print(build(args.root, args.output))
