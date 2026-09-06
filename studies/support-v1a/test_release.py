import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from release_data import check_public, digest, make_archive, public_files, unpack_archive


class ReleaseTests(unittest.TestCase):
    def test_archive_preserves_bytes_and_omits_only_operational_files(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            root = base / "source"
            root.mkdir()
            (root / "manifest.json").write_text('{"source": "public"}\n')
            (root / "local.json").write_text('{"source": "/Users/private/source"}\n')
            (root / "supervisor.log").write_text("private process paths\n")
            chunk = root / "chunks/validation/example/000000/attempt-001"
            chunk.mkdir(parents=True)
            data = b'{"index": 0, "state": "*ERROR*"}\n'
            (chunk / "runs.jsonl").write_bytes(data)
            before = digest(chunk / "runs.jsonl")
            archive = base / "main.tar.gz"
            info = make_archive(root, "main", archive)
            target = base / "extracted"
            unpack_archive(archive, info, target)
            self.assertEqual((target / "main/chunks/validation/example/000000/attempt-001/runs.jsonl").read_bytes(), data)
            self.assertEqual(info["omitted_operational_files"], ["local.json", "supervisor.log"])
            self.assertFalse((target / "main/local.json").exists())
            self.assertEqual(digest(chunk / "runs.jsonl"), before)

    def test_build_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            root = base / "source"
            root.mkdir()
            (root / "protocol.json").write_text("{}\n")
            a, b = base / "a.tar.gz", base / "b.tar.gz"
            make_archive(root, "main", a)
            make_archive(root, "main", b)
            self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_private_paths_addresses_hosts_and_image_ids_rejected(self):
        values = [b"/Users/someone/project", b"/home/someone/project", b"10.1.2.3", b"192.168.1.20",
                  b"172.16.0.1", b"host.local", b"sha256:" + b"a" * 64]
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_public("main/manifest.json", value)
        with self.assertRaises(ValueError):
            check_public("main/manifest.json", b"personal-host", ["personal-host"])

    def test_upstream_source_and_unknown_files_rejected(self):
        for name in ("main/groups.ss", "main/Dockerfile", "main/Metacat-1.2.tgz", "main/source.py"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                check_public(name, b"content")

    def test_relative_paths_and_operational_files_rejected(self):
        for name in ("../manifest.json", "/main/manifest.json", "main/../manifest.json", "main/local.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                check_public(name, b"{}")

    def test_symlink_and_unclassified_root_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "manifest.json").symlink_to("missing")
            with self.assertRaises(ValueError):
                public_files(root)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "secret.txt").write_text("secret")
            with self.assertRaises(ValueError):
                public_files(root)

    def test_corrupt_archive_and_inventory_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            root = base / "source"
            root.mkdir()
            (root / "manifest.json").write_text("{}\n")
            archive = base / "main.tar.gz"
            info = make_archive(root, "main", archive)
            bad = json.loads(json.dumps(info))
            bad["scientific_files"]["manifest.json"] = "0" * 64
            with self.assertRaises(ValueError):
                unpack_archive(archive, bad, base / "bad-inventory")
            archive.write_bytes(archive.read_bytes() + b"changed")
            with self.assertRaises(ValueError):
                unpack_archive(archive, info, base / "bad-archive")

    def test_archive_symlink_cannot_escape_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            archive = base / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                entry = tarfile.TarInfo("main/manifest.json")
                entry.type, entry.linkname = tarfile.SYMTYPE, "/tmp/escape"
                tar.addfile(entry)
            info = {"sha256": digest(archive), "bytes": archive.stat().st_size, "root": "main"}
            with self.assertRaises(ValueError):
                unpack_archive(archive, info, base / "target")


if __name__ == "__main__":
    unittest.main()
