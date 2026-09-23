import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo


ACADEMIC = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("supplement", ACADEMIC / "tools/package_experiments.py")
PACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACK)


class SupplementTests(unittest.TestCase):
    def test_unsafe_and_hidden_paths_are_rejected(self):
        for name in ("../secret", "/absolute", "a/../../secret", "a\\secret", ".git/config", "a//b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                PACK.safe_name(name)

    def test_private_identifiers_are_rejected(self):
        for content in (b"/Users/researcher/work", b"10.20.30.40", b"https://github.com/ExampleOwner/Petacat"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                PACK.scan("data/example.json", content)
        with self.assertRaises(ValueError):
            PACK.scan("README.md", b"Named Researcher", ["named researcher"])

    def test_synthetic_privacy_fixture_exception_is_file_scoped(self):
        PACK.scan("studies/support-v1a/test_release.py", b"10.20.30.40")
        with self.assertRaises(ValueError):
            PACK.scan("studies/support-v1a/collect.py", b"10.20.30.40")

    def test_frozen_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.zip"
            metadata = {"files": {"data.json": {"sha256": PACK.digest(b"original"), "bytes": 8}}}
            with ZipFile(path, "w") as archive:
                for name, content in ((PACK.INDEX, PACK.encoded(metadata)), ("data.json", b"modified")):
                    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, content)
            with self.assertRaisesRegex(ValueError, "hash/length"):
                PACK.verify_zip(path)

    def test_only_documentation_can_replace_frozen_source(self):
        self.assertEqual(PACK.REVIEW_DOCS, {"Metacat/README.md", "studies/support-v1a/README.md"})
        self.assertEqual(set(PACK.OMIT_SOURCE), {"Metacat/gui-validation.png"})

    def test_license_redaction_preserves_terms(self):
        original = b"# License\nCopyright (c) 2026 Example Author\nPermission is hereby granted.\n"
        revised = PACK.review_license(original)
        self.assertNotIn(b"Example Author", revised)
        self.assertIn(b"Copyright (c) 2026 Anonymous author", revised)
        self.assertTrue(revised.endswith(b"Permission is hereby granted.\n"))
        with self.assertRaises(ValueError):
            PACK.review_license(b"No copyright line")


if __name__ == "__main__":
    unittest.main()
