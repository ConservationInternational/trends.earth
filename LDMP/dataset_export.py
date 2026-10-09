"""Package datasets, including their full VRT dependency chains, into zip files.

Exported archives use a flat layout because dataset import looks for each
result file next to the job JSON. Any VRT reference whose target is placed
under a different archive name is rewritten to a relative sibling path.
"""

import ntpath
import os
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import defusedxml.ElementTree as DefusedET
from defusedxml import DefusedXmlException

_VRT_SOURCE_TAGS = ("SourceFilename", "SourceDataset")
_SIDECAR_SUFFIXES = (".aux.xml", ".ovr", ".msk")


@dataclass
class ExportSummary:
    archived_files: list[Path] = field(default_factory=list)
    rewritten_vrts: list[Path] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)


def _is_vsi_path(path: str) -> bool:
    return path.replace("\\", "/").startswith("/vsi")


def _is_absolute_source(path: str) -> bool:
    return posixpath.isabs(path) or ntpath.isabs(path)


def _is_relative_to_vrt(element) -> bool:
    for name, value in element.attrib.items():
        if name.lower() == "relativetovrt":
            return value.strip() == "1"
    return False


def _set_relative_to_vrt(element) -> None:
    for name in list(element.attrib):
        if name.lower() == "relativetovrt":
            del element.attrib[name]
    element.set("relativeToVRT", "1")


def _resolve_source(vrt_path: Path, element) -> Path | None:
    source = (element.text or "").strip()
    if not source or _is_vsi_path(source):
        return None

    if _is_absolute_source(source) or not _is_relative_to_vrt(element):
        candidates = [source]
    else:
        candidates = [
            os.path.join(vrt_path.parent, source),
            os.path.join(vrt_path.parent, source.replace("\\", os.sep)),
        ]

    for candidate in candidates:
        if os.path.exists(candidate):
            return Path(candidate).resolve()
    return Path(candidates[-1])


def _read_vrt(path: Path):
    """Parse a VRT, or return None if it is unreadable or uses DTD entities."""
    try:
        return DefusedET.parse(path)
    except (DefusedET.ParseError, DefusedXmlException, OSError):
        return None


def _source_elements(tree):
    for tag in _VRT_SOURCE_TAGS:
        yield from tree.iter(tag)


def _is_vrt(path: Path) -> bool:
    return path.suffix.lower() == ".vrt"


def _sidecars(path: Path) -> list[Path]:
    return [
        sidecar
        for sidecar in (Path(f"{path}{suffix}") for suffix in _SIDECAR_SUFFIXES)
        if sidecar.is_file()
    ]


def _unique_name(path: Path, used_names: set[str]) -> str:
    name = path.name
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while name.lower() in used_names:
        name = f"{stem}_{counter}{suffix}"
        counter += 1
    used_names.add(name.lower())
    return name


def collect_dataset_files(paths) -> tuple[list[Path], list[str]]:
    """Return existing files needed by ``paths`` and unresolved references.

    VRT sources are followed recursively. Sidecar files, such as ``.aux.xml``
    metadata and external overviews, are included when present.
    """
    ordered: list[Path] = []
    seen: set[Path] = set()
    missing: list[str] = []
    pending = [Path(path) for path in paths if path is not None]

    while pending:
        path = pending.pop(0)
        if _is_vsi_path(str(path)):
            continue
        if not path.is_file():
            missing.append(str(path))
            continue

        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(resolved)
        pending.extend(_sidecars(resolved))

        if not _is_vrt(resolved):
            continue
        tree = _read_vrt(resolved)
        if tree is None:
            continue
        for element in _source_elements(tree):
            dependency = _resolve_source(resolved, element)
            if dependency is not None:
                pending.append(dependency)

    return ordered, list(dict.fromkeys(missing))


def _rewrite_vrt(path: Path, archive_names: dict[Path, str]) -> bytes | None:
    tree = _read_vrt(path)
    if tree is None:
        return None

    changed = False
    for element in _source_elements(tree):
        dependency = _resolve_source(path, element)
        if dependency is None or dependency not in archive_names:
            continue

        new_source = archive_names[dependency]
        old_source = (element.text or "").strip()
        if old_source != new_source or not _is_relative_to_vrt(element):
            element.text = new_source
            _set_relative_to_vrt(element)
            changed = True

    if not changed:
        return None
    return DefusedET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=False)


def write_dataset_archive(
    target_path: Path, data_paths, extra_paths=()
) -> ExportSummary:
    """Write a flat dataset archive containing every VRT dependency.

    ``data_paths`` are dataset result files. ``extra_paths`` are files such as
    the job JSON and metadata, which are archived without dependency scanning.
    """
    data_files, missing = collect_dataset_files(data_paths)
    extra_files = []
    seen = set(data_files)
    for extra_path in extra_paths:
        extra = Path(extra_path).resolve()
        if extra not in seen:
            seen.add(extra)
            extra_files.append(extra)

    used_names: set[str] = set()
    archive_names = {
        path: _unique_name(path, used_names) for path in [*extra_files, *data_files]
    }
    summary = ExportSummary(missing_files=missing)

    target_path = Path(target_path)
    temporary_target = target_path.with_name(f"{target_path.name}.partial")
    try:
        with ZipFile(temporary_target, "w", compression=ZIP_DEFLATED) as archive:
            for path in [*extra_files, *data_files]:
                rewritten = _rewrite_vrt(path, archive_names) if _is_vrt(path) else None
                if rewritten is None:
                    archive.write(path, archive_names[path])
                else:
                    archive.writestr(archive_names[path], rewritten)
                    summary.rewritten_vrts.append(path)
                summary.archived_files.append(path)
        os.replace(temporary_target, target_path)
    except BaseException:
        temporary_target.unlink(missing_ok=True)
        raise

    return summary
