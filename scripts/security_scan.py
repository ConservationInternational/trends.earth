#!/usr/bin/env python3
"""Run the QGIS Plugin Repository security checks on a plugin ZIP."""

import argparse
import json
import os
import subprocess
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

SECURITY_CONFIG_FILES = {".bandit", ".secrets.baseline", ".flake8"}
HIDDEN_ALLOWLIST = {".gitignore", ".gitattributes", *SECURITY_CONFIG_FILES}
SUSPICIOUS_EXTENSIONS = (".exe", ".dll", ".so", ".dylib", ".bat", ".sh", ".ps1", ".cmd")


def load_rules(rules_file):
    with rules_file.open(encoding="utf-8") as stream:
        return json.load(stream)


def run_command(command, cwd=None):
    environment_executable = Path(sys.executable).with_name(command[0])
    if environment_executable.is_file():
        command[0] = str(environment_executable)
    elif shutil.which(command[0]) is None:
        raise RuntimeError(f"Required scanner not installed: {command[0]}")
    try:
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise RuntimeError(f"Required scanner not installed: {command[0]}") from error


def report_findings(title, findings):
    print(f"{title}: {len(findings)} issue(s)")
    for finding in findings:
        print(f"  {finding}")


def scan_bandit(scan_root, rules):
    enabled = rules["bandit"]["enabled"]
    command = ["bandit", "-r", str(scan_root), "-f", "json", "--quiet"]
    if enabled:
        command.extend(["-t", ",".join(enabled)])
    else:
        command.append("-ll")

    result = run_command(command)
    try:
        findings = json.loads(result.stdout or "{}").get("results", [])
    except json.JSONDecodeError as error:
        raise RuntimeError("Bandit returned invalid JSON output") from error
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Bandit failed with exit code {result.returncode}: {result.stderr.strip()}")

    formatted = []
    for issue in findings:
        formatted.append(
            f"{issue.get('filename', '')}:{issue.get('line_number', 0)} - "
            f"{issue.get('test_id', '')}: {issue.get('issue_text', '')}"
        )
    report_findings("Bandit", formatted)
    return bool(findings)


def scan_secrets(scan_root, plugin_root, rules):
    disabled = rules["secrets"]["disabled"]
    command = [
        "detect-secrets",
        "scan",
        "--all-files",
        "--exclude-files",
        r"metadata\.txt",
        "--exclude-files",
        r"\.secrets\.baseline",
    ]
    baseline = plugin_root / ".secrets.baseline"
    if baseline.is_file():
        command.extend(["--baseline", os.path.relpath(baseline, scan_root)])
    for plugin in disabled:
        command.extend(["--disable-plugin", plugin])
    command.append(".")

    result = run_command(command, cwd=scan_root)
    if result.returncode:
        raise RuntimeError(
            f"detect-secrets failed with exit code {result.returncode}: {result.stderr.strip()}"
        )
    try:
        results = json.loads(result.stdout or "{}").get("results", {})
    except json.JSONDecodeError as error:
        raise RuntimeError("detect-secrets returned invalid JSON output") from error

    formatted = [
        f"{path}:{finding.get('line_number', 0)} - {finding.get('type', 'Unknown')}"
        for path, findings in sorted(results.items())
        for finding in findings
        if not path.endswith((".pyc", ".pyo", ".so", ".dll", ".exe"))
    ]
    report_findings("detect-secrets", formatted)
    return bool(formatted)


def scan_flake8(scan_root, plugin_root, rules):
    enabled = rules["flake8"]["enabled"]
    python_files = sorted(str(path) for path in scan_root.rglob("*.py"))
    if not python_files:
        print("Flake8: no Python files found (informational)")
        return

    command = ["flake8", "--max-line-length=120"]
    config = scan_root / ".flake8"
    if not config.is_file():
        config = next(
            (
                child / ".flake8"
                for child in scan_root.iterdir()
                if child.is_dir() and (child / ".flake8").is_file()
            ),
            None,
        )
    if config:
        command.extend(["--config", str(config)])
    if enabled:
        command.extend(["--select", ",".join(enabled)])
    command.extend(python_files)

    result = run_command(command)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Flake8 failed with exit code {result.returncode}: {result.stderr.strip()}")
    findings = result.stdout.splitlines()
    report_findings("Flake8 (informational)", findings)


def scan_archive_files(archive_path, rules):
    enabled = set(rules["file_analysis"]["enabled"])
    executable_python = []
    suspicious = []
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            filename = entry.filename
            basename = Path(filename).name
            if filename.endswith(".py") and (entry.external_attr >> 16) & 0o111:
                if "FILE_EXECUTABLE" in enabled:
                    executable_python.append(filename)
            if basename.startswith(".") and basename not in HIDDEN_ALLOWLIST:
                if "FILE_HIDDEN" in enabled:
                    suspicious.append(f"{filename} - Hidden file detected")
            for extension in SUSPICIOUS_EXTENSIONS:
                if filename.lower().endswith(extension):
                    if "FILE_SUSPICIOUS" in enabled:
                        suspicious.append(
                            f"{filename} - Executable or binary file detected ({extension})"
                        )
                    break

    report_findings(
        "File permissions (informational)",
        [f"{name} - Python file has executable permission" for name in executable_python],
    )
    report_findings("Suspicious files (informational)", suspicious)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Packaged plugin ZIP to scan")
    parser.add_argument("--plugin-name", default="LDMP", help="Top-level plugin directory in the ZIP")
    args = parser.parse_args()

    archive_path = args.archive.resolve()
    if not archive_path.is_file():
        parser.error(f"Plugin ZIP not found: {archive_path}")

    try:
        rules = load_rules(Path(__file__).with_name("security_scan_rules.json"))
        with tempfile.TemporaryDirectory() as temporary_dir:
            scan_root = Path(temporary_dir)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(scan_root)
            plugin_root = scan_root / args.plugin_name
            if not plugin_root.is_dir():
                raise RuntimeError(f"Plugin directory {args.plugin_name} not found in {archive_path}")

            bandit_failed = scan_bandit(scan_root, rules)
            secrets_failed = scan_secrets(scan_root, plugin_root, rules)
            scan_flake8(scan_root, plugin_root, rules)
            scan_archive_files(archive_path, rules)

        if bandit_failed or secrets_failed:
            print("Critical Bandit or secrets findings block this plugin version.")
            return 1
        return 0
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Security scan failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
