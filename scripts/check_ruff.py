"""Run a full Ruff scan and fail only on diagnostics absent from the base."""

import argparse
import json
import subprocess
import tarfile
import tempfile
from collections import Counter
from pathlib import Path


def scan(root):
    result = subprocess.run(
        ["ruff", "check", "--output-format=json", "--exclude=gee,notebooks", "."],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Ruff failed:\n{result.stderr}")
    return json.loads(result.stdout)


def fingerprint(diagnostic, root):
    path = Path(diagnostic["filename"])
    line = path.read_text(encoding="utf-8").split("\n")[
        diagnostic["location"]["row"] - 1
    ]
    return (
        path.relative_to(root).as_posix(),
        diagnostic["code"],
        diagnostic["message"],
        line.strip(),
    )


def new_diagnostics(base, current, base_root, current_root):
    remaining = Counter(fingerprint(item, base_root) for item in base)
    added = []
    for item in current:
        key = fingerprint(item, current_root)
        if remaining[key]:
            remaining[key] -= 1
        else:
            added.append(item)
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_ref", help="PR base SHA or the default branch ref")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    base_ref = args.base_ref
    base_sha = subprocess.check_output(
        ["git", "rev-parse", base_ref], cwd=root, text=True
    ).strip()
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if base_sha == head_sha:
        # On a default-branch push, compare with the previous commit.
        base_ref = "HEAD^"
    current = scan(root)
    with tempfile.TemporaryDirectory(
        prefix="trends-earth-ruff-", dir=root.parent
    ) as directory:
        base_root = Path(directory)
        archive = base_root / "base.tar"
        with archive.open("wb") as output:
            subprocess.run(
                ["git", "archive", "--format=tar", base_ref],
                cwd=root,
                stdout=output,
                check=True,
            )
        with tarfile.open(archive) as source:
            source.extractall(base_root, filter="data")
        base = scan(base_root)
        added = new_diagnostics(base, current, base_root, root)
    for item in added:
        path = Path(item["filename"]).relative_to(root).as_posix()
        location = item["location"]
        message = f"{item['code']} {item['message']}"
        print(
            f"::error file={path},line={location['row']},"
            f"col={location['column']}::{message}"
        )
    print(
        f"Ruff: {len(current)} current diagnostics, {len(base)} base diagnostics, "
        f"{len(added)} new diagnostics."
    )
    return bool(added)


if __name__ == "__main__":
    raise SystemExit(main())
