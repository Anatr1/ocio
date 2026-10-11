"""Content hashes for models (including NCNN directories) and renderer bundles."""
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path


def file_hash(path):
    path = Path(path)
    h = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    if not files:
        raise ValueError(f"empty model directory: {path}")
    for file in files:
        if path.is_dir():
            h.update(file.relative_to(path).as_posix().encode() + b"\0")
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def implementation_stamp():
    root = Path(__file__).resolve().parents[1]
    files = sorted([*(root / "crosswalk").rglob("*.py"), *(root / "sim").glob("*.py"),
                    *(root / "sim/scenarios").glob("*.yaml")])
    hashes = {p.relative_to(root).as_posix(): file_hash(p) for p in files}
    packages = {}
    for name in ("numpy", "opencv-python", "scipy", "onnxruntime", "playwright", "PyYAML"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {"code_hash": json_hash(hashes), "files": hashes, "packages": packages}
