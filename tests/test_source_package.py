"""Source distribution metadata must identify the bytes actually delivered."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_package", ROOT / "scripts/package-source.py")
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class SourcePackageTest(unittest.TestCase):
    def test_exact_clean_and_modified_source_archives(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = directory / "source"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "node_modules", ".pytest_cache", "dist"))
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), "-c", "user.name=Source Test",
                    "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", *args],
                    stderr=subprocess.PIPE)
            git("init", "-q")
            git("add", ".")
            git("commit", "-qm", "source fixture")
            output = directory / "source.tar.gz"
            result = PACKAGE.package(root, output)
            self.assertFalse(result["modified"])
            self.assertEqual(result["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            with tarfile.open(output) as archive:
                metadata = json.load(archive.extractfile("ai-docs/SOURCE.json"))
                self.assertFalse(metadata["modified"])
                self.assertEqual(metadata["base_commit"], git("rev-parse", "HEAD").decode().strip())
                for name, digest in metadata["files"].items():
                    self.assertEqual(hashlib.sha256(archive.extractfile("ai-docs/" + name).read()).hexdigest(), digest)
                self.assertFalse(any(".git/" in member.name or "__pycache__" in member.name for member in archive))
            with self.assertRaises(FileExistsError):
                PACKAGE.package(root, output)
            (root / "README.md").write_text("Modified candidate\n")
            candidate = directory / "candidate.tar.gz"
            with self.assertRaises(ValueError):
                PACKAGE.package(root, candidate)
            self.assertTrue(PACKAGE.package(root, candidate, allow_dirty=True)["modified"])
            with self.assertRaises(ValueError):
                PACKAGE.package(root, root / "forbidden.tar.gz", allow_dirty=True)
            (root / "unsafe-link").symlink_to(directory)
            with self.assertRaises(ValueError):
                PACKAGE.package(root, directory / "unsafe.tar.gz", allow_dirty=True)


if __name__ == "__main__":
    unittest.main()
