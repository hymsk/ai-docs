#!/usr/bin/env python3
"""Read-only tarball/member/license audit; never installs or executes packages.

Supply one or more --archive-dir directories containing name-version.tgz
(@scope/name is stored as @scope__name). With --download, missing archives are
downloaded to a TemporaryDirectory and deleted on exit. No repository writes.
"""

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
import subprocess
import tarfile
import tempfile
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normalize(raw, entry):
    mode = entry["normalization"]
    if mode == "none":
        return raw
    if mode == "crlf-to-lf-and-ensure-final-lf":
        raw = raw.replace(b"\r\n", b"\n")
        return raw if raw.endswith(b"\n") else raw + b"\n"
    if mode == "byte-ranges-joined-with-lf-and-final-lf":
        ranges = entry["source_ranges"]
        require(all(0 <= a <= b <= len(raw) for a, b in ranges), "invalid source range")
        return b"\n".join(raw[a:b] for a, b in ranges) + b"\n"
    raise ValueError("unknown normalization: " + mode)


def github_file(entry, source_path, expected_sha256, directories, download, temporary):
    """Read a commit-pinned file; cache by SHA-256, never execute downloaded data."""
    repository, commit = entry["source_repository"], entry["source_commit"]
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository), "invalid repository")
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "GitHub source must be commit-pinned")
    require(re.fullmatch(r"[A-Za-z0-9_./-]+", source_path) and not source_path.startswith("/")
            and ".." not in Path(source_path).parts, "unsafe GitHub path")
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha256), "invalid source digest")
    filename = expected_sha256 + ".source"
    path = next((d / filename for d in directories if (d / filename).is_file()), None)
    if path is not None:
        raw = path.read_bytes()
    else:
        require(download, "missing GitHub source cache: " + filename + "; use --download")
        path = Path(temporary) / (filename + ".json")
        url = "https://api.github.com/repos/{}/contents/{}?ref={}".format(repository, source_path, commit)
        subprocess.run(["curl", "--disable", "--fail", "--silent", "--show-error",
                        "--proto", "=https", "--connect-timeout", "10", "--max-time", "30",
                        url, "--output", str(path)], check=True)
        data = json.loads(path.read_bytes())
        require(data.get("type") == "file" and data.get("encoding") == "base64"
                and data.get("path") == source_path, "unexpected GitHub response")
        raw = base64.b64decode("".join(data["content"].split()), validate=True)
        require(git_blob(raw) == data["sha"], "GitHub blob mismatch")
    require(digest(raw) == expected_sha256, "GitHub source digest mismatch")
    return raw


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", action="append", type=Path, default=[])
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "licenses/manifest.json").read_text())
    provenance = json.loads((ROOT / "scripts/vendor-provenance.json").read_text())
    packages = {(p["name"], p["version"]): p for p in manifest["packages"]}
    require(len(packages) == len(manifest["packages"]), "duplicate package")
    handles = {}
    paths = {}
    with tempfile.TemporaryDirectory(prefix="ai-docs-provenance-") as tmp:
        try:
            for key, package in packages.items():
                name, version = key
                filename = name.replace("/", "__") + "-" + version + ".tgz"
                candidates = [directory / filename for directory in args.archive_dir]
                path = next((p for p in candidates if p.is_file()), None)
                if path is None:
                    require(args.download, "missing archive: " + filename)
                    url = package["source_url"]
                    parsed = urlparse(url)
                    require(parsed.scheme == "https" and parsed.netloc == "registry.npmjs.org", "unexpected archive host")
                    path = Path(tmp) / filename
                    subprocess.run(["curl", "--disable", "--fail", "--silent", "--show-error",
                                    "--location", "--proto", "=https", "--proto-redir", "=https",
                                    "--connect-timeout", "10", "--max-time", "120", url,
                                    "--output", str(path)], check=True)
                require(digest(path.read_bytes()) == package["archive_sha256"], "archive digest: " + filename)
                paths[key] = path
                handles[key] = tarfile.open(path, "r:gz")

            def member(key, path):
                require(path.startswith("package/") and ".." not in Path(path).parts, "unsafe archive member")
                info = handles[key].getmember(path)
                require(info.isfile(), "not a regular archive member: " + path)
                return handles[key].extractfile(info).read()

            for key in packages:
                data = json.loads(member(key, "package/package.json"))
                require((data["name"], data["version"]) == key, "package identity mismatch")

            for entry in manifest["vendor_files"]:
                raw = member((entry["package"], entry["version"]), entry["source_path"])
                require(raw == (ROOT / entry["file"]).read_bytes(), "vendor byte mismatch: " + entry["file"])
                require(digest(raw) == entry["sha256"], "vendor digest: " + entry["file"])

            for entry in manifest["files"]:
                key = (entry["package"], entry["version"])
                if entry.get("source_type", "npm-member") == "github-file":
                    expected_url = "https://raw.githubusercontent.com/{}/{}/{}".format(
                        entry["source_repository"], entry["source_commit"], entry["source_path"])
                    require(entry["source_url"] == expected_url, "GitHub URL identity mismatch")
                    raw = github_file(entry, entry["source_path"], entry["source_sha256"],
                                      args.archive_dir, args.download, tmp)
                    require(git_blob(raw) == entry["source_blob_sha1"], "license Git blob mismatch")
                    match = entry["npm_member_match"]
                    upstream = github_file(entry, match["source_path"], match["sha256"],
                                           args.archive_dir, args.download, tmp)
                    require(upstream == member(key, match["npm_path"]), "GitHub/npm source mismatch")
                else:
                    require(entry.get("source_type", "npm-member") == "npm-member", "unknown source type")
                    raw = member(key, entry["source_path"])
                require(digest(raw) == entry["source_sha256"], "member digest: " + entry["file"])
                local = normalize(raw, entry)
                require(local == (ROOT / entry["file"]).read_bytes(), "license byte mismatch: " + entry["file"])
                require(digest(local) == entry["sha256"], "license digest: " + entry["file"])

            url_keys = {p["source_url"]: key for key, p in packages.items()}
            for evidence in manifest["evidence"]:
                raw = member(url_keys[evidence["source_url"]], evidence["source_path"])
                require(digest(raw) == evidence["source_sha256"], "evidence member digest: " + evidence["id"])
                for observation in evidence["observations"]:
                    if "byte_range" in observation:
                        a, b = observation["byte_range"]
                        actual = raw[a:b].decode()
                    else:
                        actual = json.loads(raw)
                        for part in observation["json_pointer"].split("/")[1:]:
                            part = part.replace("~1", "/").replace("~0", "~")
                            actual = actual[int(part)] if isinstance(actual, list) else actual[part]
                    require(actual == observation["value"], "evidence observation: " + evidence["id"])

            mermaid_map = json.loads(member(("mermaid", "11.17.2"), "package/dist/mermaid.min.js.map"))
            count = 0
            for entry in provenance["mermaid_dependencies"]:
                for index in entry["byte_identical_indices"]:
                    source = mermaid_map["sources"][index]
                    path = "package/" + source.rsplit("/node_modules/" + entry["name"] + "/", 1)[1]
                    raw = member((entry["name"], entry["version"]), path)
                    require(raw == mermaid_map["sourcesContent"][index].encode(), "Mermaid source content: " + source)
                    count += 1
            md_map = json.loads(member(("markdown-it", "14.3.2"), "package/dist/markdown-it.min.js.map"))
            for entry in provenance["markdown_it_source_members"]:
                raw = member((entry["package"], entry["version"]), entry["member"])
                require(raw == md_map["sourcesContent"][entry["index"]].encode(), "markdown-it source content")
                require(digest(raw) == entry["archive_member_sha256"], "markdown-it source digest")
            print("Verified {} archives, {} exact vendor files, {} license/notice payloads; {} Mermaid and {} markdown-it source members.".format(
                len(packages), len(manifest["vendor_files"]), len(manifest["files"]), count,
                len(provenance["markdown_it_source_members"])))
            print("Scope: pinned npm members and declared commit-pinned GitHub payloads/member matches; external lockfiles/advisory snapshots and legal completeness are not revalidated.")
        finally:
            for handle in handles.values():
                handle.close()


if __name__ == "__main__":
    main()
