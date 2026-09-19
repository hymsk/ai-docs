#!/usr/bin/env python3
"""Validate the standalone release metadata and vendored browser assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VENDOR_HASHES = {
    "d3.min.js": "d6b03aefc9f6c44c7bc78713679c78c295028fa914319119e5cc4b4954855b1c",
    "echarts.min.js": "bf4a223524e40b77c304bec67e1222cf551f14880cf42c69dc046558e11c07b1",
    "highlight.min.js": "c4a399dd6f488bc97a3546e3476747b3e714c99c57b9473154c6fb8d259b9381",
    "highlight-styles.css": "3a9a5def8b9c311e5ae43abde85c63133185eed4f0d9f67fea4b00a8308cf066",
    "katex.min.css": "f787891b550d554c214aa8902f39ac46df2dbd48fdec500a2040a5dce1e8ab58",
    "katex.min.js": "863811e2baa0849c77bc92d26d44f4d0a4843c2a8ab52c462017dea57316e4d8",
    "markdown-it.min.js": "e32488403e2e565ac12a9669bfdf2b1b876eb0a5c84f8e0699884b562d18eb52",
    "markmap-lib.browser.js": "7fa851eda0f0eaf08a88d8894c843a987934bc029dbe0df5901698897ae4131b",
    "markmap-view.browser.js": "98770326cd0014f7bcfaaf906316ab6aba170239a93098d5857298f59be405ab",
    "mermaid.min.js": "581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8",
}
SKIP_DIRECTORIES = frozenset((".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", "dist", "htmlcov"))
FORBIDDEN_PATTERNS = (
    (re.compile(r"/" + r"root/"), "developer absolute path"),
    (re.compile(r"hymsk" + r"\.top", re.IGNORECASE), "personal service domain"),
    (re.compile(r"(?:gitee|github)\.com/[^/\s]+/" + r"ai-stor\b", re.IGNORECASE), "internal repository URL"),
    (re.compile(r"tools/" + r"codeagent/"), "private integration path"),
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer [A-Za-z0-9._~+/-]{20,}"),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_text(content: str, label: str) -> list[str]:
    """Report rules and paths only; never echo potentially secret content."""
    errors = ["{} contains {}".format(label, rule)
              for pattern, rule in FORBIDDEN_PATTERNS if pattern.search(content)]
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        errors.append("{} contains a credential-like value".format(label))
    return errors


def safe_label(value: str) -> str:
    """Paths and ref names may themselves contain secrets or terminal escapes."""
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        return "redacted-name-sha256:" + hashlib.sha256(value.encode()).hexdigest()[:16]
    return value.encode("unicode_escape").decode("ascii")


def private_config_name(name: str) -> bool:
    return name in (".env", ".token") or name.startswith(".env.") and not name.endswith(".example")


def scan_tree(root: Path) -> list[str]:
    errors = []
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in names + files:
            path = base / name
            if name != ".git" and path.is_symlink():
                errors.append("{} is a symlink".format(safe_label(str(path.relative_to(root)))))
        names[:] = sorted(name for name in names
                          if name not in SKIP_DIRECTORIES and not (base / name).is_symlink())
        for name in sorted(files):
            path = base / name
            if name == ".git" or path.is_symlink() or path.suffix in (".pyc", ".pyo"):
                continue
            relative = str(path.relative_to(root))
            label = safe_label(relative)
            errors.extend(scan_text(relative, "file name " + label))
            if private_config_name(name):
                errors.append("{} is a private configuration file".format(label))
                continue
            raw = path.read_bytes()
            if b"\0" not in raw:
                errors.extend(scan_text(raw.decode("utf-8", errors="replace"), label))
    return errors


def scan_history(root: Path) -> list[str]:
    """Scan local reachable files, commit metadata, ref names and annotated tags.

    No fetching, history rewriting, allowlisting or remote-setting changes.
    """
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)

    if not (root / ".git").exists():
        return ["history check requires this repository's Git metadata"]
    errors = []
    seen = set()
    try:
        if git("rev-parse", "--is-shallow-repository").strip() == b"true":
            errors.append("history check requires complete local history, not a shallow clone")
        seen_tags = set()
        for record in git("for-each-ref", "--format=%(objectname) %(objecttype) %(refname)").decode().splitlines():
            oid, kind, ref = record.split(" ", 2)
            errors.extend(scan_text(ref, "ref " + safe_label(ref)))
            while kind == "tag" and oid not in seen_tags:
                seen_tags.add(oid)
                raw = git("cat-file", "tag", oid).decode("utf-8", errors="replace")
                errors.extend(scan_text(raw, oid[:12] + ":annotated-tag"))
                header = dict(line.split(" ", 1) for line in raw.split("\n\n", 1)[0].splitlines() if " " in line)
                oid, kind = header.get("object", ""), header.get("type", "")
        for commit in git("rev-list", "--all", "HEAD").decode().splitlines():
            metadata = git("cat-file", "commit", commit).decode("utf-8", errors="replace")
            errors.extend(scan_text(metadata, commit[:12] + ":commit-metadata"))
            for entry in git("ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
                if not entry:
                    continue
                metadata, name = entry.split(b"\t", 1)
                mode, kind, oid = metadata.decode().split()
                if kind != "blob":
                    continue
                decoded_name = name.decode("utf-8", errors="replace")
                label = "{}:{}".format(commit[:12], safe_label(decoded_name))
                errors.extend(scan_text(decoded_name, "file name " + label))
                if private_config_name(Path(decoded_name).name):
                    errors.append(label + " is a private configuration file")
                if mode == "120000":
                    errors.append(label + " is a symlink")
                if oid in seen:
                    continue
                seen.add(oid)
                raw = git("cat-file", "blob", oid)
                if b"\0" not in raw:
                    errors.extend(scan_text(raw.decode("utf-8", errors="replace"), label))
    except subprocess.CalledProcessError:
        errors.append("history check failed to read local Git objects")
    return errors


def check_licenses(root: Path) -> list[str]:
    errors = []
    try:
        manifest = json.loads((root / "licenses/manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1 or not manifest.get("files"):
            return ["invalid license manifest schema"]
        if manifest.get("hash_algorithm") != "sha256" or manifest.get("path_base") != "repository-root":
            errors.append("invalid license manifest hash algorithm or path base")
        def sha(value):
            return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

        packages = {}
        for package in manifest["packages"]:
            key = (package["name"], package["version"])
            if not all(isinstance(value, str) and value for value in key) or key in packages:
                errors.append("invalid or duplicate license package")
            if not isinstance(package["source_url"], str) or not package["source_url"].startswith("https://registry.npmjs.org/") or not sha(package["archive_sha256"]):
                errors.append("invalid license package provenance")
            packages[key] = package["source_url"]
        for entry in manifest["files"] + manifest["vendor_files"]:
            key = (entry["package"], entry["version"])
            if key not in packages:
                errors.append("license entry references unknown package/version")
            source = entry["source_path"]
            if entry.get("source_type", "npm-member") == "github-file":
                repository = entry["source_repository"]
                commit = entry["source_commit"]
                if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not re.fullmatch(r"[0-9a-f]{40}", commit):
                    errors.append("invalid pinned GitHub source")
                if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", source) or source.startswith("/") or ".." in Path(source).parts:
                    errors.append("invalid GitHub member path")
                if entry["source_url"] != "https://raw.githubusercontent.com/{}/{}/{}".format(repository, commit, source):
                    errors.append("GitHub source URL differs from pinned identity")
                if not re.fullmatch(r"[0-9a-f]{40}", entry["source_blob_sha1"]):
                    errors.append("invalid Git blob identity")
                match = entry["npm_member_match"]
                if not re.fullmatch(r"[A-Za-z0-9_./-]+", match["source_path"]) or match["source_path"].startswith("/") or ".." in Path(match["source_path"]).parts or match["npm_path"] != "package/" + match["source_path"] or not sha(match["sha256"]):
                    errors.append("invalid GitHub/npm member correspondence")
                if entry not in manifest["files"] or entry["normalization"] != "none":
                    errors.append("GitHub sources only support unmodified license payloads")
            else:
                if entry.get("source_type", "npm-member") != "npm-member":
                    errors.append("unknown license source type")
                if "source_url" in entry and entry["source_url"] != packages.get(key):
                    errors.append("license entry source URL differs from package")
                if not isinstance(source, str) or not source.startswith("package/") or ".." in Path(source).parts:
                    errors.append("invalid license upstream member path")
            if not sha(entry["sha256"]) or "source_sha256" in entry and not sha(entry["source_sha256"]):
                errors.append("invalid license digest format")
        names = set()
        for entry in manifest["files"]:
            relative = entry["file"]
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or not relative.startswith("licenses/") or relative in names:
                errors.append("invalid or duplicate license manifest path")
                continue
            names.add(relative)
            target = root / path
            if target.is_symlink() or not target.is_file() or digest(target) != entry["sha256"]:
                errors.append("license digest mismatch or missing file: {}".format(relative))
        actual = {path.relative_to(root).as_posix() for path in (root / "licenses").rglob("*") if path.is_file()}
        if actual != names | {"licenses/manifest.json", "licenses/README.md", "licenses/verify-provenance.py"}:
            errors.append("license file set does not match manifest")
        vendors = manifest["vendor_files"]
        if {entry["file"] for entry in vendors} != {"scripts/vendor/" + name for name in VENDOR_HASHES}:
            errors.append("license manifest vendor set mismatch")
        for entry in vendors:
            if entry["sha256"] != VENDOR_HASHES.get(Path(entry["file"]).name):
                errors.append("license manifest vendor digest mismatch")
            if not entry["license_files"] or not set(entry["license_files"]) <= names:
                errors.append("license manifest references missing attribution")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        errors.append("cannot validate license manifest")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="also scan locally reachable Git history")
    args = parser.parse_args()
    errors = []
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:rc[1-9]\d*)?", version):
        errors.append("VERSION must be a release or rc version")

    manager_source = (ROOT / "scripts" / "web-mcp-manager.py").read_text(encoding="utf-8")
    server_source = (ROOT / "web-mcp" / "source" / "ai_docs_web.py").read_text(encoding="utf-8")
    if 'VERSION = "{}"'.format(version) not in manager_source:
        errors.append("web-mcp-manager.py version does not match VERSION")
    if 'SERVER_VERSION = "{}"'.format(version) not in server_source:
        errors.append("ai_docs_web.py version does not match VERSION")

    required = (
        "LICENSE",
        "README.md",
        "SKILL.md",
        "AGENTS.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "THIRD_PARTY_NOTICES.md",
    )
    for relative in required:
        if not (ROOT / relative).is_file():
            errors.append("missing {}".format(relative))
    for relative in ("README.md", "CHANGELOG.md"):
        if version not in (ROOT / relative).read_text(encoding="utf-8"):
            errors.append("{} does not mention VERSION".format(relative))

    vendor_dir = ROOT / "scripts" / "vendor"
    actual_vendor_names = {path.name for path in vendor_dir.iterdir() if path.is_file()}
    if actual_vendor_names != set(VENDOR_HASHES):
        errors.append("vendor file set does not match THIRD_PARTY_NOTICES.md")
    for name, expected in VENDOR_HASHES.items():
        path = vendor_dir / name
        if path.is_file() and digest(path) != expected:
            errors.append("vendor digest mismatch: {}".format(name))

    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for name, expected in VENDOR_HASHES.items():
        if name not in notices or expected not in notices:
            errors.append("THIRD_PARTY_NOTICES.md is missing {} provenance".format(name))

    resources = json.loads((ROOT / "assets" / "default-resources.json").read_text(encoding="utf-8"))
    referenced_vendor_names = {
        Path(value["source"]).name
        for value in resources.values()
        if isinstance(value, dict) and isinstance(value.get("source"), str)
        and "scripts/vendor/" in value["source"]
    }
    # ECharts is consumed directly by the Node renderer for static SSR rather
    # than emitted through the browser resource manifest.
    referenced_vendor_names.add("echarts.min.js")
    if referenced_vendor_names != set(VENDOR_HASHES):
        errors.append("default-resources.json vendor set does not match release manifest")

    errors.extend(check_licenses(ROOT))
    errors.extend(scan_tree(ROOT))
    if args.history:
        errors.extend(scan_history(ROOT))

    if errors:
        print("AI Docs release check failed:")
        for error in errors:
            print("- {}".format(error))
        return 1
    print("AI Docs release check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
