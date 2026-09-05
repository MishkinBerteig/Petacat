import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


BUNDLE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('reconstruct', BUNDLE / 'tools/reconstruct.py')
reconstruct = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reconstruct)


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'example.ss').write_text('(exit)\n')
        (self.source / 'example.ss').chmod(0o644)
        self.files = {'example.ss': {
            'sha256': reconstruct.digest(self.source / 'example.ss'),
            'executable': False,
        }}

    def test_valid_inventory(self):
        reconstruct.verify(self.source, self.files)

    def test_changed_file_rejected(self):
        (self.source / 'example.ss').write_text('(exit 1)\n')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            reconstruct.verify(self.source, self.files)

    def test_missing_file_rejected(self):
        (self.source / 'example.ss').unlink()
        with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
            reconstruct.verify(self.source, self.files)

    def test_extra_file_rejected(self):
        (self.source / 'extra.ss').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
            reconstruct.verify(self.source, self.files)

    def test_symlink_rejected(self):
        original = self.source / 'example.ss'
        original.rename(self.root / 'external.ss')
        original.symlink_to(self.root / 'external.ss')
        with self.assertRaisesRegex(ValueError, 'Not a regular file'):
            reconstruct.verify(self.source, self.files)

    def test_executable_permission_checked(self):
        (self.source / 'example.ss').chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'permission mismatch'):
            reconstruct.verify(self.source, self.files)

    def test_extra_directory_symlink_rejected(self):
        (self.root / 'external').mkdir()
        (self.source / 'extra').symlink_to(self.root / 'external', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Not a regular file'):
            reconstruct.verify(self.source, self.files)

    def test_unsafe_paths_rejected(self):
        for name in ('../outside', '/outside', 'a/../../outside'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                reconstruct.safe_path(self.source, name)

    def test_existing_destination_is_not_replaced(self):
        with self.assertRaisesRegex(ValueError, 'Refusing to replace'):
            reconstruct.reconstruct(self.root / 'absent.tgz', self.source, {})
        self.assertEqual((self.source / 'example.ss').read_text(), '(exit)\n')

    def test_corrupt_archive_rejected_before_output_created(self):
        archive = self.root / 'corrupt.tgz'
        archive.write_bytes(b'not the upstream archive')
        output = self.root / 'new-source'
        manifest = json.loads((BUNDLE / 'manifest.json').read_text())
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            reconstruct.reconstruct(archive, output, manifest)
        self.assertFalse(output.exists())

    def test_bundle_patch_checksums(self):
        manifest = json.loads((BUNDLE / 'manifest.json').read_text())
        for patch in manifest['patches']:
            reconstruct.check_digest(BUNDLE / patch['path'], patch['sha256'])

    def test_bundle_does_not_ship_upstream_source_or_archives(self):
        manifest = json.loads((BUNDLE / 'manifest.json').read_text())
        upstream_names = {Path(name).name for name in manifest['upstream']['files']
                          if name.endswith('.ss')}
        for path in BUNDLE.rglob('*'):
            if not path.is_file() or path.relative_to(BUNDLE).parts[0] == 'build':
                continue
            with self.subTest(path=path.relative_to(BUNDLE)):
                self.assertNotIn(path.name, upstream_names)
                self.assertFalse(path.name.endswith(('.tgz', '.tar.gz', '.zip')))

    def test_gui_patch_uses_portable_directories(self):
        patch = (BUNDLE / 'patches/0001-engine.patch').read_text()
        self.assertIn('+(define *platform* \'linux)', patch)
        self.assertIn('+(define *metacat-directory* '
                      '(string-append (current-directory) "/"))', patch)
        self.assertIn('+(define *file-dialog-directory* *metacat-directory*)', patch)

    def test_manifest_contains_no_machine_capture_metadata(self):
        manifest = json.loads((BUNDLE / 'manifest.json').read_text())
        self.assertNotIn('modified', manifest)
        self.assertNotIn('captured_date', manifest)


if __name__ == '__main__':
    unittest.main()
