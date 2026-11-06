"""Manifest of a restoration progress report: job, scope, inputs, versions,
parameters, checksums, validation and export status."""

import hashlib
import json
from pathlib import Path

MANIFEST_NAME = "Report_Manifest.json"


def sha256(path: Path) -> str:
    """SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_value(value):
    """JSON value of a date, a datetime (ISO 8601) or another object (text)."""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def write_manifest(output_dir: Path, manifest: dict) -> Path:
    """Write the manifest in MANIFEST_NAME of the output folder.

    The checksums are the SHA-256 of every file of the output folder, by its
    path in the folder, except the manifest.
    """
    path = output_dir / MANIFEST_NAME
    manifest["checksums"] = {
        file.relative_to(output_dir).as_posix(): sha256(file)
        for file in sorted(output_dir.rglob("*"))
        if file.is_file() and file != path
    }
    path.write_text(
        json.dumps(manifest, indent=2, default=_json_value), encoding="utf-8"
    )
    return path
