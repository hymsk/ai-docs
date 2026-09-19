#!/usr/bin/env python3
"""Create an auditable source-only archive outside this checkout (never publish)."""

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def package(root, output, allow_dirty=False):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)

    root = root.resolve()
    output = output.resolve()
    if output == root or root in output.parents:
        raise ValueError("source archive must be outside the checkout")
    dirty = bool(git("status", "--porcelain", "--untracked-files=all"))
    if dirty and not allow_dirty:
        raise ValueError("checkout is dirty; --allow-dirty creates a candidate, not a release")
    spec = importlib.util.spec_from_file_location("release_check", root / "scripts/check-release.py")
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    if checks.scan_tree(root) or checks.check_licenses(root):
        raise ValueError("source or license checks failed; run scripts/check-release.py for redacted diagnostics")
    names = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")) - {""})
    files = {}
    for name in names:
        path = root / name
        if not path.exists() and dirty:
            continue
        if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
            raise ValueError("source archive requires regular in-tree files")
        if any(part in checks.SKIP_DIRECTORIES for part in Path(name).parts) or path.suffix in (".pyc", ".pyo"):
            raise ValueError("generated or excluded file in source inventory")
        files[name] = path.read_bytes()
    if "SOURCE.json" in files:
        raise ValueError("SOURCE.json is reserved for generated archive metadata")
    metadata = {
        "schema_version": 1,
        "version": (root / "VERSION").read_text().strip(),
        "base_commit": git("rev-parse", "HEAD").decode().strip(),
        "modified": dirty,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
    }
    files["SOURCE.json"] = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()
    # Exclusive output creation prevents overwriting an existing release asset.
    with output.open("xb") as handle:
        with tarfile.open(fileobj=handle, mode="w:gz") as archive:
            for name, raw in sorted(files.items()):
                info = tarfile.TarInfo("ai-docs/" + name)
                info.size = len(raw)
                info.mode = 0o755 if (root / name).exists() and (root / name).stat().st_mode & 0o111 else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(raw))
    return {"sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "modified": dirty, "file_count": len(files)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-dirty", action="store_true", help="make an explicitly marked uncommitted candidate")
    args = parser.parse_args()
    try:
        print(json.dumps(package(ROOT, args.output, args.allow_dirty), sort_keys=True))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, "Source packaging failed: {}\n".format(type(error).__name__) +
                    "Check clean Git state, source/license checks and an unused external output path.\n")
