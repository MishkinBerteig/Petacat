from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import package_submission as package


def inner_zip(content):
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        info = ZipInfo("example.txt", date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = 0o100644 << 16
        archive.writestr(info, content)
    return stream.getvalue()


class SubmissionPackageTests(unittest.TestCase):
    def files(self):
        return {"README.md": b"Anonymous review evidence",
                package.MEMBERS[1]: inner_zip(b"saved observations"),
                package.MEMBERS[2]: inner_zip(b"anonymous manuscript source")}

    def test_exact_deterministic_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = (Path(directory) / n for n in ("first.zip", "second.zip"))
            files = self.files()
            package.write_bundle(first, files)
            package.write_bundle(second, files)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(set(package.verify_bundle(first)["files"]), set(files))
            with ZipFile(first) as archive:
                for name, body in files.items():
                    self.assertEqual(archive.read(name), body)

    def test_unexpected_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            package.write_bundle(Path("unused.zip"), {**self.files(), "private.txt": b"excluded"})

    def test_private_token_inside_inner_zip_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upload.zip"
            files = self.files()
            files[package.MEMBERS[1]] = inner_zip(b"Example Author Identity")
            package.write_bundle(path, files)
            with self.assertRaisesRegex(ValueError, "private token"):
                package.verify_bundle(path, ["author identity"])

    def test_tampered_inner_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            good, bad = (Path(directory) / n for n in ("good.zip", "bad.zip"))
            package.write_bundle(good, self.files())
            with ZipFile(good) as source, ZipFile(bad, "w") as destination:
                for info in source.infolist():
                    body = b"changed" if info.filename == "README.md" else source.read(info)
                    destination.writestr(info, body)
            with self.assertRaisesRegex(ValueError, "hash/length"):
                package.verify_bundle(bad)

    def test_identifying_archive_comment_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upload.zip"
            package.write_bundle(path, self.files())
            with ZipFile(path, "a") as archive:
                archive.comment = b"Unwanted identifying metadata"
            with self.assertRaises(ValueError):
                package.verify_bundle(path)


if __name__ == "__main__":
    unittest.main()
