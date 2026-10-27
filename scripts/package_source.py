"""Allowlisted source archives and offline release packaging helpers (Python 3.12)."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

VERSION = "0.4.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", ".gitignore",
    "requirements.txt", "requirements-build.txt", "JinshuDialogue.spec",
    "CONTRIBUTING.md", "SECURITY.md", ".editorconfig", ".gitattributes",
}
SCRIPT_FILES = {"scripts/build.ps1", "scripts/package_source.py", "scripts/check_docs.py"}
GITHUB_FILES = {".github/workflows/windows.yml", ".github/ISSUE_TEMPLATE/bug_report.yml",
                ".github/ISSUE_TEMPLATE/feature_request.yml", ".github/ISSUE_TEMPLATE/config.yml",
                ".github/pull_request_template.md"}
DOC_FILES = {"docs/architecture.md", "docs/development.md", "docs/compatibility.md",
             "docs/releasing.md", "docs/documentation.md", "docs/release-notes-template.md"}
DENIED_PARTS = {
    ".git", ".venv", "venv", "vendor", "runtime", "diagnostics", "tools", "data",
    "settings", "对话记录", "__pycache__", ".build", "build", "dist", "release",
    ".codex", ".agents", "node_modules",
}
DENIED_NAMES = {"config.json", "settings.json", "implementation.md"}


def allowed_source_path(relative: Path) -> bool:
    """A new top-level directory never becomes public by accident."""
    parts = relative.parts
    name = relative.as_posix()
    if any(part.casefold() in DENIED_PARTS for part in parts):
        return False
    if relative.name.casefold() in DENIED_NAMES:
        return False
    if len(parts) == 1:
        return name in ROOT_FILES
    if name in SCRIPT_FILES or name in GITHUB_FILES:
        return True
    suffix = relative.suffix.lower()
    if parts[0] == "src":
        return len(parts) == 2 and suffix in {".py", ".js", ".qss"}
    if parts[0] == "profiles":
        return len(parts) == 2 and suffix == ".json"
    if parts[0] == "assets":
        return suffix in {".png", ".ico", ".svg", ".qss", ".json", ".md", ".txt"}
    if parts[0] == "tests":
        return suffix in {".py", ".js", ".json"}
    if parts[:2] == ("scripts", "licenses"):
        return suffix in {".txt", ".md", ".json"} or relative.name in {"COPYING", "LICENSE"}
    if name in DOC_FILES:
        return True
    if parts[:2] == ("docs", "screenshots"):
        return suffix in {".png", ".jpg", ".jpeg", ".webp"}
    return False


def is_link(path: Path):
    return path.is_symlink() or path.is_junction()


def checked_files(root: Path):
    """Do not follow links or package content from outside the checkout."""
    for directory, children, names in os.walk(root, followlinks=False):
        folder = Path(directory)
        children[:] = sorted(child for child in children
                             if child.casefold() not in DENIED_PARTS and not is_link(folder / child))
        for name in sorted(names):
            path = folder / name
            if not path.is_file() or is_link(path) or not path.resolve().is_relative_to(root):
                continue
            yield path, path.relative_to(root)


def source_files(root: Path):
    candidates = [root / name for name in ROOT_FILES | SCRIPT_FILES | GITHUB_FILES | DOC_FILES]
    for directory in ("src", "profiles", "assets", "tests", "scripts/licenses", "docs/screenshots"):
        source = root / directory
        if source.is_dir() and not is_link(source):
            candidates.extend(path for path, _ in checked_files(source))
    files = []
    for path in sorted(set(candidates)):
        if not path.is_file() or is_link(path) or not path.resolve().is_relative_to(root):
            continue
        relative = path.relative_to(root)
        if any(is_link(root / Path(*relative.parts[:index])) for index in range(1, len(relative.parts))):
            continue
        if allowed_source_path(relative):
            files.append((path, relative))
    return files


def write_archive(files, destination: Path, prefix: str):
    """Replace one archive atomically, without deleting an output directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path, relative in files:
                archive.write(path, f"{prefix}/{relative.as_posix()}")
        temporary.replace(destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def package_source(root: Path, destination: Path):
    files = source_files(root)
    included = {relative.as_posix() for _, relative in files}
    required = ROOT_FILES | SCRIPT_FILES | GITHUB_FILES | DOC_FILES | {"src/gui.py", "src/agent.js", "src/theme.qss"}
    missing = sorted(required - included)
    if missing:
        raise ValueError(f"Source package is missing required files: {', '.join(missing)}")
    if not any(relative.parts[0] == "profiles" for _, relative in files):
        raise ValueError("Source package needs at least one profiles/*.json file.")
    write_archive(files, destination, f"JinshuDialogue-{VERSION}-source")
    print(f"Source archive: {destination} ({len(files)} files)")


def collect_licenses(root: Path, destination: Path):
    """Gather original installed license texts plus checked-in official fallbacks."""
    destination.mkdir(parents=True, exist_ok=True)
    cache = root / "scripts" / "licenses"
    manifest = cache / "SOURCES.json"
    if not manifest.is_file():
        raise ValueError("Missing scripts/licenses/SOURCES.json; cannot build complete notices offline.")
    sources = json.loads(manifest.read_text(encoding="utf-8"))
    for entry in sources["files"]:
        source = cache / entry["path"]
        if not source.resolve().is_relative_to(cache.resolve()):
            raise ValueError(f"Unsafe license path: {source}")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"License cache hash mismatch: {source}")
        target = destination / "upstream" / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(manifest, destination / "SOURCES.json")
    packages = []
    for name in ("frida", "PySide6-Essentials", "shiboken6", "PyInstaller"):
        dist = metadata.distribution(name)
        license_files = []
        for relative in dist.files or []:
            if any("license" in part.lower() or "copying" in part.lower() for part in relative.parts):
                source = Path(dist.locate_file(relative))
                if not source.is_file() or source.suffix.lower() in {".py", ".pyc", ".pyd"}:
                    continue
                target = destination / name / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                license_files.append(target.relative_to(destination).as_posix())
        packages.append({"name": name, "version": dist.version, "license_files": license_files})
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        python_license = Path(sys.base_prefix) / "LICENSE"
    if not python_license.is_file():
        raise ValueError("Cannot locate Python runtime license.")
    shutil.copy2(python_license, destination / "Python-LICENSE.txt")
    packages.append({"name": "Python", "version": sys.version.split()[0], "license_files": ["Python-LICENSE.txt"]})
    (destination / "DEPENDENCIES.json").write_text(json.dumps(packages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Offline license collection: {destination} ({len(sources['files'])} cached upstream files)")


def package_application(directory: Path, destination: Path):
    if not (directory / "JinshuDialogue.exe").is_file():
        raise ValueError("Application directory is missing JinshuDialogue.exe.")
    files = []
    for path, relative in checked_files(directory):
        if relative.as_posix() in {"JinshuDialogue.exe", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md"} | DOC_FILES:
            files.append((path, relative))
        elif relative.parts[0] in {"_internal", "LICENSES"}:
            files.append((path, relative))
        elif relative.parts[:2] == ("docs", "screenshots") and relative.suffix.lower() == ".png":
            files.append((path, relative))
    required = {"README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "LICENSES/SOURCES.json"}
    missing = required - {relative.as_posix() for _, relative in files}
    if missing:
        raise ValueError(f"Application package is missing notices: {sorted(missing)}")
    write_archive(files, destination, f"JinshuDialogue-{VERSION}-windows-x64")
    print(f"Application archive: {destination} ({len(files)} files)")


def write_checksums(files: list[Path], output: Path):
    lines = []
    for path in files:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(f"{digest}  {path.name}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"SHA-256 checksums: {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--list", action="store_true", help="Preview source allowlist, without writing files.")
    parser.add_argument("--output", type=Path, help="Create a source ZIP at this path.")
    parser.add_argument("--collect-licenses", type=Path, metavar="DIRECTORY")
    parser.add_argument("--application-dir", type=Path)
    parser.add_argument("--application-output", type=Path)
    parser.add_argument("--checksums", nargs="+", type=Path)
    parser.add_argument("--checksums-output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.list:
        for _, relative in source_files(root):
            print(relative.as_posix())
    if args.output:
        package_source(root, args.output.resolve())
    if args.collect_licenses:
        collect_licenses(root, args.collect_licenses.resolve())
    if args.application_dir:
        if not args.application_output:
            parser.error("--application-dir requires --application-output")
        package_application(args.application_dir.resolve(), args.application_output.resolve())
    if args.checksums:
        if not args.checksums_output:
            parser.error("--checksums requires --checksums-output")
        write_checksums(args.checksums, args.checksums_output)
    if not (args.list or args.output or args.collect_licenses or args.application_dir or args.checksums):
        parser.error("Choose --list, --output, --collect-licenses, --application-dir or --checksums.")


if __name__ == "__main__":
    main()
