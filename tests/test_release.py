"""Release checks must detect regressions without printing secret fixtures."""

import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_check", ROOT / "scripts/check-release.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ReleaseCheckTest(unittest.TestCase):
    def test_license_manifest_and_missing_file(self):
        self.assertEqual(CHECK.check_licenses(ROOT), [])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "licenses", root / "licenses")
            manifest = json.loads((root / "licenses/manifest.json").read_text())
            (root / manifest["files"][0]["file"]).unlink()
            self.assertTrue(CHECK.check_licenses(root))

    def test_literal_private_domains_and_paths(self):
        for value in ("hymsk" + ".top", "https://gitee.com/example/" + "ai-stor",
                      "tools/" + "codeagent/skills/example", "/" + "root/work/project"):
            self.assertTrue(CHECK.scan_text(value, "fixture"))
        self.assertEqual(CHECK.scan_text("https://docs.example.com /absolute/path/to/node", "fixture"), [])
        self.assertEqual(CHECK.scan_text("hymskXtop", "fixture"), [])

    def test_license_provenance_mutations_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "licenses", root / "licenses")
            path = root / "licenses/manifest.json"
            original = path.read_text(encoding="utf-8")
            for field, value in (("version", "0.0.0"), ("source_url", "https://example.invalid/source"), ("source_sha256", "invalid")):
                manifest = json.loads(original)
                manifest["files"][0][field] = value
                path.write_text(json.dumps(manifest), encoding="utf-8")
                self.assertTrue(CHECK.check_licenses(root), field)

    def test_secret_is_not_echoed(self):
        value = "ghp_" + "a" * 32
        errors = CHECK.scan_text(value, "fixture")
        self.assertTrue(errors)
        self.assertNotIn(value, "\n".join(errors))

    def test_github_license_requires_immutable_identity_and_member_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "licenses", root / "licenses")
            path = root / "licenses/manifest.json"
            original = path.read_text()
            for field, value in (("source_commit", "master"), ("source_repository", "../boolbase"),
                                 ("source_path", "../LICENSE"), ("source_type", "unknown"),
                                 ("source_blob_sha1", "invalid"), ("normalization", "unknown")):
                manifest = json.loads(original)
                entry = next(e for e in manifest["files"] if e.get("source_type") == "github-file")
                entry[field] = value
                path.write_text(json.dumps(manifest))
                self.assertTrue(CHECK.check_licenses(root), field)
            manifest = json.loads(original)
            entry = next(e for e in manifest["files"] if e.get("source_type") == "github-file")
            entry["npm_member_match"]["npm_path"] = "package/other.js"
            path.write_text(json.dumps(manifest))
            self.assertTrue(CHECK.check_licenses(root))

    def test_nested_extensionless_and_symlink_scan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "nested" / "NOTICE").write_text("/" + "root/private", encoding="utf-8")
            (root / "link").symlink_to("nested", target_is_directory=True)
            (root / ".git").write_text("gitdir: /" + "root/private", encoding="utf-8")
            errors = CHECK.scan_tree(root)
            self.assertTrue(any("NOTICE" in error for error in errors))
            self.assertTrue(any("symlink" in error for error in errors))
            self.assertFalse(any(".git" in error for error in errors))

    def test_history_detects_removed_content_without_mutating_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
            git("init", "-q")
            (root / "nested").mkdir()
            path = root / "nested/example.md"
            path.write_text("ghp_" + "b" * 32, encoding="utf-8")
            (root / "nested/link").symlink_to("example.md")
            git("add", "nested")
            git("-c", "user.name=Release Test", "-c", "user.email=test@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
            path.write_text("safe", encoding="utf-8")
            before = git("status", "--porcelain")
            errors = CHECK.scan_history(root)
            self.assertTrue(any("nested/example.md" in error and "credential" in error for error in errors))
            self.assertTrue(any("nested/link" in error and "symlink" in error for error in errors))
            self.assertEqual(before, git("status", "--porcelain"))

    def test_history_metadata_names_and_private_config_are_scanned_without_echo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            secret = "ghp_" + "c" * 32
            def git(*args):
                return subprocess.check_output([
                    "git", "-C", str(root), "-c", "user.name=Release Test",
                    "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
                    "-c", "tag.gpgsign=false", *args], stderr=subprocess.PIPE)
            git("init", "-q")
            (root / secret).write_text("safe")
            (root / ".env").write_text("configuration without a known secret pattern")
            git("add", ".")
            git("commit", "-qm", secret)
            git("tag", "-a", secret, "-m", secret)
            before = git("status", "--porcelain")
            errors = CHECK.scan_history(root)
            output = "\n".join(errors)
            for label in ("commit-metadata", "annotated-tag", "ref ", "file name ", "private configuration"):
                self.assertIn(label, output)
            self.assertNotIn(secret, output)
            self.assertNotIn(secret, "\n".join(CHECK.scan_tree(root)))
            self.assertEqual(before, git("status", "--porcelain"))
            clone = root / "shallow"
            git("clone", "--depth=1", root.as_uri(), str(clone))
            self.assertTrue(any("shallow" in item for item in CHECK.scan_history(clone)))


if __name__ == "__main__":
    unittest.main()
