"""Fetch one author-attributed, CC-BY scanned human from the public Objaverse archive.

No models with non-commercial/unclear licences are accepted.
"""
import gzip
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.fetch_sim_assets import fetch

UID = "3a606acdfbe04478b0ab8dfe0f1de978"  # Dima, scanned and published by in3D.
BASE = "https://huggingface.co/datasets/allenai/objaverse/resolve/main/"


def main():
    index = ROOT / "runs/asset-index/object-paths.json.gz"
    fetch(BASE + "object-paths.json.gz", index)
    with gzip.open(index, "rt", encoding="utf-8") as f:
        paths = json.load(f)
    if UID not in paths:
        raise RuntimeError("the selected scan is not in the public archive")
    # The archive's metadata is authoritative for the per-object licence.
    shard = paths[UID].split("/")[1]
    metadata = ROOT / f"runs/asset-index/{shard}.json.gz"
    fetch(BASE + f"metadata/{shard}.json.gz", metadata)
    with gzip.open(metadata, "rt", encoding="utf-8") as f:
        annotation = json.load(f)[UID]
    licence = annotation.get("license")
    if isinstance(licence, dict):
        licence = licence.get("slug")
    if licence not in ("by", "cc0"):
        raise ValueError(f"refusing licence {licence}: {annotation.get('license')}")
    destination = ROOT / "sim/render/assets/human-scan.glb"
    url = BASE + paths[UID]
    sha = fetch(url, destination)
    (destination.parent / "human-scan-LICENSE.json").write_text(json.dumps(annotation, indent=2), encoding="utf-8")
    manifest_path = destination.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets/human-scan.glb"] = {"url": url, "sha256": sha, "source": annotation.get("viewerUrl"),
                                       "author": annotation.get("user"), "licence": annotation.get("license")}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("ready:", destination, "licence:", licence)


if __name__ == "__main__":
    main()
