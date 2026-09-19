"""Offline tests for immutable GitHub source recovery; no network calls."""

import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
import base64

ROOT = Path(__file__).resolve().parents[1]
AUDIT = runpy.run_path(str(ROOT / "licenses/verify-provenance.py"))


class ProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.entry = next(e for e in json.loads((ROOT / "licenses/manifest.json").read_text())["files"]
                          if e.get("source_type") == "github-file")
        self.raw = (ROOT / self.entry["file"]).read_bytes()

    def test_original_license_blob_and_offline_cache(self):
        self.assertEqual(AUDIT["git_blob"](self.raw), self.entry["source_blob_sha1"])
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), self.entry["source_sha256"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / (self.entry["source_sha256"] + ".source")
            with self.assertRaisesRegex(ValueError, "missing GitHub source cache"):
                AUDIT["github_file"](self.entry, "LICENSE", self.entry["source_sha256"], [Path(directory)], False, directory)
            path.write_bytes(self.raw)
            self.assertEqual(AUDIT["github_file"](self.entry, "LICENSE", self.entry["source_sha256"],
                                                [Path(directory)], False, directory), self.raw)
            path.write_bytes(self.raw + b"changed")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                AUDIT["github_file"](self.entry, "LICENSE", self.entry["source_sha256"], [Path(directory)], False, directory)

    def test_download_checks_response_blob_and_digest(self):
        response = {"type": "file", "encoding": "base64", "path": "LICENSE",
                    "sha": self.entry["source_blob_sha1"], "content": base64.b64encode(self.raw).decode()}
        def download(args, **kwargs):
            self.assertIn("?ref=" + self.entry["source_commit"], args[-3])
            Path(args[-1]).write_text(json.dumps(response))
        with tempfile.TemporaryDirectory() as directory, patch("subprocess.run", side_effect=download):
            self.assertEqual(AUDIT["github_file"](self.entry, "LICENSE", self.entry["source_sha256"], [], True, directory), self.raw)
            response["sha"] = "0" * 40
            with self.assertRaisesRegex(ValueError, "blob mismatch"):
                AUDIT["github_file"](self.entry, "LICENSE", self.entry["source_sha256"], [], True, directory)

    def test_unpinned_or_unsafe_sources_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for field, value in (("source_commit", "master"), ("source_repository", "../boolbase")):
                with self.assertRaises(ValueError):
                    AUDIT["github_file"](dict(self.entry, **{field: value}), "LICENSE", self.entry["source_sha256"], [], False, directory)
            for path in ("../LICENSE", "/LICENSE", "LICENSE?ref=master"):
                with self.assertRaises(ValueError):
                    AUDIT["github_file"](self.entry, path, self.entry["source_sha256"], [], False, directory)


if __name__ == "__main__":
    unittest.main()
