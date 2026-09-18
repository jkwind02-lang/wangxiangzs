"""Verify imported upstream bytes, paths, and recorded source version. Read only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def verify(root: Path = ROOT) -> int:
    manifest = json.loads((root / "UPSTREAM_IMPORT.json").read_text(encoding="utf-8"))
    source = json.loads((root / "UPSTREAM.json").read_text(encoding="utf-8"))
    for key in ("repository", "commit", "tree"):
        if manifest.get(key) != source.get(key):
            raise ValueError("Upstream version mismatch: " + key)
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise ValueError("Missing upstream file manifest")
    seen = set()
    for item in records:
        rel = PurePosixPath(item["target_path"])
        if rel.is_absolute() or any(p in {".", "..", ".git"} for p in rel.parts):
            raise ValueError("Unsafe manifest path")
        if rel.as_posix().casefold() in seen:
            raise ValueError("Duplicate manifest path")
        seen.add(rel.as_posix().casefold())
        path = root.joinpath(*rel.parts)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Missing or unsafe upstream file: " + str(rel))
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Upstream SHA256 mismatch: " + str(rel))
        git_blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if git_blob != item["git_blob"]:
            raise ValueError("Upstream Git blob mismatch: " + str(rel))
    print(f"Verified {len(records)} unchanged upstream files at {manifest['commit']}")
    return len(records)


if __name__ == "__main__":
    verify()
