from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools import prepare_repository as importer


def manifest(root, entries=None):
    if entries is None:
        entries = [{"path": p.relative_to(root).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in root.rglob("*") if p.is_file() and p.name != "UPGRADE_FILES.json"]
    (root / "UPGRADE_FILES.json").write_text(json.dumps({"files": entries}), encoding="utf-8")


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.package = base / "package"; self.package.mkdir()
        self.dest = base / "destination"; self.dest.mkdir()
        (self.package / "README.md").write_text("new docs", encoding="utf-8")
        (self.package / ".gitignore").write_text(".env\n.local/\n", encoding="utf-8")
        (self.package / "new.py").write_text("pass\n", encoding="utf-8")
        (self.dest / "README.md").write_text("upstream docs", encoding="utf-8")
        manifest(self.package)
    def tearDown(self): self.tmp.cleanup()
    def test_preserve_upstream_readme(self):
        importer.apply_overlay(self.package, self.dest)
        self.assertEqual((self.dest / "UPSTREAM_README.md").read_text(), "upstream docs")
        self.assertEqual((self.dest / "README.md").read_text(), "new docs")
    def test_hash_mismatch_before_writes(self):
        (self.package / "new.py").write_text("tampered")
        with self.assertRaises(ValueError): importer.apply_overlay(self.package, self.dest)
        self.assertFalse((self.dest / "UPSTREAM_README.md").exists())
    def test_unexpected_collision_before_writes(self):
        (self.dest / "new.py").write_text("user work")
        with self.assertRaises(ValueError): importer.apply_overlay(self.package, self.dest)
        self.assertEqual((self.dest / "new.py").read_text(), "user work")
        self.assertFalse((self.dest / "UPSTREAM_README.md").exists())
    def test_traversal_rejected(self):
        manifest(self.package, [{"path": "../escape.py", "sha256": "x"}])
        with self.assertRaises(ValueError): importer.overlay_plan(self.package, self.dest)
    def test_git_directory_rejected(self):
        manifest(self.package, [{"path": ".git/config", "sha256": "x"}])
        with self.assertRaises(ValueError): importer.overlay_plan(self.package, self.dest)
    def test_secret_file_rejected(self):
        manifest(self.package, [{"path": ".env", "sha256": "x"}])
        with self.assertRaises(ValueError): importer.overlay_plan(self.package, self.dest)
    def test_gitignore_combined(self):
        (self.dest / ".gitignore").write_text("upstream-cache/\n")
        importer.apply_overlay(self.package, self.dest)
        self.assertIn("upstream-cache/", (self.dest / ".gitignore").read_text())
        self.assertIn(".env", (self.dest / ".gitignore").read_text())
    def test_existing_destination_never_cloned_over(self):
        with self.assertRaises(ValueError): importer.prepare(self.dest)
    def test_real_local_git_preserves_history_and_stages_overlay(self):
        source = Path(self.tmp.name) / "source"; source.mkdir()
        def run(*args):
            return subprocess.check_output(["git", "-C", str(source), *args], encoding="utf-8").strip()
        run("init", "-b", "main")
        run("config", "user.name", "Fixture")
        run("config", "user.email", "fixture@example.invalid")
        (source / "README.md").write_text("upstream docs")
        run("add", "README.md"); run("commit", "-m", "fixture initial")
        commit = run("rev-parse", "HEAD"); tree = run("rev-parse", "HEAD^{tree}")
        dest = Path(self.tmp.name) / "full-clone"
        with patch.object(importer, "UPSTREAM", str(source)), patch.object(importer, "COMMIT", commit), patch.object(importer, "TREE", tree), patch.object(importer, "ROOT", self.package), redirect_stdout(io.StringIO()):
            importer.prepare(dest)
        self.assertEqual(importer.git(dest, "rev-parse", "main"), commit)
        self.assertEqual(importer.git(dest, "branch", "--show-current"), importer.BRANCH)
        self.assertEqual(importer.git(dest, "remote", "get-url", "origin"), importer.TARGET)
        self.assertIn("new.py", importer.git(dest, "diff", "--cached", "--name-only"))
        self.assertEqual(importer.git(dest, "rev-list", "--count", "HEAD"), "1")

if __name__ == "__main__": unittest.main()
